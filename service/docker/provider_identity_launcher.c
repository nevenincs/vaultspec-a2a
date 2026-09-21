#define _GNU_SOURCE

#include <errno.h>
#include <grp.h>
#include <linux/capability.h>
#include <linux/prctl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

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

int main(int argc, char **argv) {
    if (argc < 5 || argv[3][0] != '-' || argv[3][1] != '-' || argv[3][2] != '\0') {
        errno = EINVAL;
        die("usage: <uid> <gid> -- <command> [args...]");
    }

    uid_t agent_uid = (uid_t)parse_identity(argv[1], "uid");
    gid_t agent_gid = (gid_t)parse_identity(argv[2], "gid");

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

    execvp(argv[4], &argv[4]);
    die("execvp(provider)");
}
