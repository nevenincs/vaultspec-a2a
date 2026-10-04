#define _GNU_SOURCE

#include <errno.h>
#include <grp.h>
#include <linux/capability.h>
#include <linux/prctl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* These identities match the image's agent account. Never take privileged
   identity authority from arguments or the caller's environment. */
#define AGENT_UID 1002
#define AGENT_GID 1002

static void die(const char *operation) {
    int saved = errno;
    fprintf(stderr, "vaultspec-agent-launch: %s failed: errno=%d\n", operation, saved);
    _exit(126);
}

static unsigned long parse_identity(const char *value, const char *name) {
    char *end = NULL;
    errno = 0;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0' || parsed > 2147483647UL) {
        errno = EINVAL;
        die(name);
    }
    return parsed;
}

static void clear_capabilities(void) {
    struct __user_cap_header_struct header = {
        .version = _LINUX_CAPABILITY_VERSION_3,
        .pid = 0,
    };
    struct __user_cap_data_struct data[2] = {{0}};

    if (syscall(SYS_capset, &header, data) != 0) {
        die("capset(clear)");
    }
    if (prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) != 0) {
        die("prctl(PR_CAP_AMBIENT_CLEAR_ALL)");
    }
    data[0] = (struct __user_cap_data_struct){0};
    data[1] = (struct __user_cap_data_struct){0};
    if (syscall(SYS_capget, &header, data) != 0) {
        die("capget(verify)");
    }
    if (data[0].effective || data[0].permitted || data[0].inheritable ||
        data[1].effective || data[1].permitted || data[1].inheritable) {
        errno = EPERM;
        die("capability postcondition");
    }
}

static void enter_agent_identity(uid_t agent_uid, gid_t agent_gid) {
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        die("prctl(PR_SET_NO_NEW_PRIVS)");
    }
    if (setgroups(0, NULL) != 0) {
        die("setgroups(clear)");
    }
    if (setgid(agent_gid) != 0) {
        die("setgid(agent)");
    }
    if (setuid(agent_uid) != 0) {
        die("setuid(agent)");
    }

    clear_capabilities();

    if (getuid() != agent_uid || geteuid() != agent_uid ||
        getgid() != agent_gid || getegid() != agent_gid) {
        errno = EPERM;
        die("identity postcondition");
    }
    int group_count = getgroups(0, NULL);
    if (group_count != 0) {
        errno = EPERM;
        die("supplementary-group postcondition");
    }
    if (prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) {
        errno = EPERM;
        die("no-new-privileges postcondition");
    }

    /* Workspace files must remain accessible to the trusted worker through the
       shared agent group; service-state creation keeps the worker's 0077 umask. */
    umask(0007);
}

/* The stdio client can signal this supervisor through its caller-owned real
   UID. Only the child executes caller-selected code. On EOF-independent
   cancellation, the supervisor enters the agent identity to reap the child's
   group, requiring no additional service capabilities. */
static void supervise_agent(uid_t uid, gid_t gid, char **command) {
    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0) {
        die("prctl(PR_SET_CHILD_SUBREAPER)");
    }
    sigset_t signals, previous;
    sigemptyset(&signals);
    sigaddset(&signals, SIGTERM);
    sigaddset(&signals, SIGINT);
    sigaddset(&signals, SIGHUP);
    if (sigprocmask(SIG_BLOCK, &signals, &previous) != 0) die("sigprocmask");
    int ready[2];
    if (pipe(ready) != 0) die("pipe");
    pid_t child = fork();
    if (child < 0) die("fork");
    if (child == 0) {
        close(ready[0]);
        if (setsid() < 0) die("setsid(agent)");
        enter_agent_identity(uid, gid);
        if (write(ready[1], "1", 1) != 1) die("signal ready");
        close(ready[1]);
        if (sigprocmask(SIG_SETMASK, &previous, NULL) != 0) die("restore signals");
        execvp(command[0], command);
        die("execvp(probe)");
    }
    close(ready[1]);
    char started;
    ssize_t count = read(ready[0], &started, 1);
    close(ready[0]);
    if (count < 0) die("read ready");
    int status = 0;
    int interrupted = 0;
    /* Keep the leader unreaped until its group is killed: its PID must not be
       reused for an unrelated group between observation and cleanup. */
    for (;;) {
        siginfo_t state = {0};
        if (waitid(P_PID, child, &state, WEXITED | WNOHANG | WNOWAIT) != 0)
            die("waitid");
        if (state.si_pid == child) break;
        struct timespec interval = {.tv_sec = 0, .tv_nsec = 10000000};
        int received = sigtimedwait(&signals, NULL, &interval);
        if (received > 0) { interrupted = received; break; }
        if (errno != EAGAIN && errno != EINTR) die("sigtimedwait");
    }
    enter_agent_identity(uid, gid);
    if (count == 1 && kill(-child, SIGKILL) != 0 && errno != ESRCH)
        die("kill(probe group)");
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) die("waitpid");
    }
    /* Reap adopted group members even when the container has no init reaper. */
    while (waitpid(-child, NULL, 0) != -1 || errno == EINTR) {}
    if (errno != ECHILD) die("waitpid(probe descendants)");
    if (interrupted) _exit(128 + interrupted);
    _exit(WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status));
}

int main(int argc, char **argv) {
    int supervise = argc > 1 && strcmp(argv[1], "--supervise") == 0;
    if (supervise) { --argc; ++argv; }
    if (argc < 5 || strcmp(argv[3], "--") != 0) {
        errno = EINVAL;
        die("usage: [--supervise] <uid> <gid> -- <command> [args...]");
    }
    uid_t agent_uid = (uid_t)parse_identity(argv[1], "uid");
    gid_t agent_gid = (gid_t)parse_identity(argv[2], "gid");
    if (agent_uid != AGENT_UID || agent_gid != AGENT_GID) {
        errno = EPERM;
        die("unconfigured agent identity");
    }
    if (supervise) supervise_agent(agent_uid, agent_gid, &argv[4]);
    enter_agent_identity(agent_uid, agent_gid);

    execvp(argv[4], &argv[4]);
    die("execvp(provider)");
}
