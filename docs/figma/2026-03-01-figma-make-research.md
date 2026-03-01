# Figma Make: Comprehensive Research

**Date:** 2026-03-01
**Status:** Research Complete
**Category:** Tooling / Design-to-Code

---

## 1. What is Figma Make?

Figma Make is an AI-powered, prompt-to-app tool built by Figma that transforms
natural language prompts, existing Figma designs, and uploaded images into
functional prototypes, interactive web apps, and editable code -- all within the
Figma environment.

It is conceptually similar to tools like Vercel's v0 and Lovable, but
differentiated by its deep integration with the Figma design ecosystem. It uses
large language models (primarily Anthropic's Claude) to generate code from
prompts and visual context.

### Target Audience

- Designers wanting to explore interactive components and prototypes
- Engineers prototyping without setting up full development stacks
- Product managers sketching out features for user testing
- Non-technical users building internal tools or MVPs
- Anyone bridging the gap between Figma designs and front-end code

---

## 2. Timeline: Announcement and Release

| Date | Milestone |
|---|---|
| **May 7, 2025** | Announced at Config 2025 in San Francisco (beta launch) |
| **August 13, 2025** | General availability -- all Figma AI features moved out of beta |
| **November 2025** | Schema 2025: Make Kits announced (early access); npm package imports begin rolling out |
| **December 2025** | Available in Figma for Government |
| **January 2026** | Claude integration for FigJam diagrams |
| **February 18, 2026** | "Code to Canvas" partnership with Anthropic launched |
| **February 20, 2026** | Custom MCP connectors + 6 new partner connectors (Amplitude, Box, Dovetail, Granola, Marvin, zeroheight) |
| **February 2026** | AI model selection: Claude Sonnet 4.6 and Claude Opus 4.6 now available in Make |
| **March 2026** | Credit-based payment system begins |

---

## 3. How Does Figma Make Generate Code?

### Input Methods

1. **Natural language prompts**: Describe the app, layout, logic, or behavior conversationally
2. **Existing Figma designs**: Attach frames, components, or Community content
3. **Image uploads**: Drag in PNG, JPG, or SVG files as visual context
4. **Figma file connections**: Connect entire Figma files for context
5. **MCP connectors**: Pull in context from Amplitude, Dovetail, Notion, GitHub, Linear, etc.

### Generation Process

- The AI chat interface accepts prompts and visual context
- The AI model (Claude Sonnet 4.6 or Opus 4.6, selectable) generates React code
- Code appears in a built-in code editor alongside a live preview
- Users iterate by continuing the conversation, selecting specific preview elements, or editing code directly
- Real-time updates: changes to layout or prompts update the React code without rebuilds

### Code Structure

- Primary entry point: `App.tsx`
- Components defined as functions with JSX
- Uses `export default` / `export` for component sharing
- Styling via Tailwind CSS utility classes
- State management via React hooks (`useState`, `useEffect`, `useRef`)
- Third-party libraries imported via standard import syntax (resolved through esm.sh CDN)
- Build system: Vite

### Known Structural Issue

All code tends to end up in a single file, which is inefficient for larger
projects. There are no sub-agents for specialized roles (unlike Claude Code).

---

## 4. Supported Frameworks

**Figma Make currently supports ONLY React (React 18+).**

- It does NOT generate Svelte, Vue, Angular, or plain HTML/CSS/JS natively
- The codebase output is React + TypeScript + Tailwind CSS
- Third-party Figma plugins (Builder.io, FireJet, Figroot, etc.) support other frameworks, but they are separate tools

---

## 5. React + Tailwind CSS Code Generation

Figma Make generates React code with Tailwind CSS styling:

- Components use `className` with Tailwind utility classes
- Dynamic props can inject values into Tailwind classes (e.g., `bg-${color}-500`)
- Components accept customizable props with default values
- A `globals.css` file is generated for base styles

### Styling Challenges

- The generated `globals.css` sometimes diverges from the variables and styles in the attached library
- Syntax errors occur in output
- For production use, manual refinement of Tailwind styling is typically needed
- Users report needing to generate CSS separately (e.g., via Figma MCP in Cursor) because the Make-generated CSS doesn't match library variables

---

## 6. How Figma Make Differs from Code Connect

| Aspect | **Figma Make** | **Code Connect** |
|---|---|---|
| **Purpose** | AI-powered design-to-code generation | Links existing code components to Figma designs |
| **Direction** | Generates NEW code from designs | Surfaces EXISTING production code in Dev Mode |
| **Output** | React apps, prototypes, web apps | Code snippets displayed in Dev Mode inspect panel |
| **Users** | Designers, PMs, non-coders, prototypers | Design system engineers, developers |
| **Code quality** | AI-generated (requires refinement) | Your actual production code |
| **Framework** | React only | React, React Native, SwiftUI, Jetpack Compose, HTML/Web Components, Storybook |
| **MCP role** | Consumer of MCP connectors for context | Provider of component mappings TO the MCP Server |
| **Plan required** | All paid plans (limited free) | Organization and Enterprise plans |

### Key Distinction

- **Make** = *generating* new code from designs (prototyping, MVPs)
- **Code Connect** = *linking* existing design system code to Figma (consistency, adoption)

---

## 7. How Figma Make Interacts with Design Tokens and Variables

### Direct Design System Integration

- Connect your team's Figma library styles and React components to keep elements on-brand
- When libraries are enabled, Make treats them as "building blocks" and generates prototypes using your actual components with defined variants, spacing tokens, and UI patterns

### Make Kits (Early Access)

Make Kits bridge Figma Design libraries and Figma Make:
- Export design libraries and convert them to React code components
- Generate CSS files for styles and variables
- Package outputs for use in Figma Make prototypes
- Currently in early access (announced Schema 2025)

### npm Package Import (GA)

- Import production React design system packages directly
- Public npm packages available to all users
- Private npm packages via Figma's managed private registry (organization scope)
- Package must be React 18+ compatible and build with Vite

### AI Guidance via Guidelines

- Add markdown files to a `guidelines/` directory to teach Make how to interpret components
- Describe when to use `<Button>` vs `<IconButton>`, required props, default variants, layout tips
- Optionally publish `guidelines.md` files in npm package versions

### Design Token Flow

- Figma variables can store design tokens (colors, spacing, typography, booleans)
- Variables import/export supports DTCG (Design Tokens Community Group) JSON format
- When using the MCP Server, variables become CSS custom properties
- Make generates a CSS file from styles and variables when using Make Kits

---

## 8. How Figma Make Uses Code Connect Mappings

### Current State

Figma Make does NOT directly consume Code Connect mappings internally. This is
a **community-requested feature** (as of early 2026).

### The MCP Bridge

The Figma MCP Server DOES consume Code Connect mappings and provides them to
external AI coding tools. The flow works like this:

1. Code Connect CLI or UI maps Figma design components to production code
2. The MCP Server wraps each connected component with:
   - Design properties (variant values, boolean props, text content)
   - Import statements
   - Actual component usage code
   - Custom instructions for AI guidance
3. External AI tools (Cursor, Claude Code, etc.) call `get_code_connect_map` to retrieve these mappings
4. Those tools then generate code using your actual design system components

### What This Means for Figma Make

- Make relies on npm packages + guidelines for design system awareness
- For production-quality code that uses your real components, the recommended path is: Figma MCP Server + Code Connect + external AI coding tool (Cursor, Claude Code)
- Make is better suited for rapid prototyping than production code generation

---

## 9. Relationship Between Make and Dev Mode

### Separate but Complementary

- **Dev Mode** = Developer-focused view for inspecting designs, extracting specs, viewing code snippets
- **Figma Make** = AI-powered generation of working prototypes and apps

### Dev Mode Features

- Component Playground: view all component variations with implementation code
- Annotations: designer markups with specs and measurements
- Ready for Dev status: signals designs are ready for implementation
- Dev Resources: links to external resources (Jira, GitHub, APIs)
- Code Connect integration: shows production code in inspect panel

### MCP Server Connection

Both Dev Mode and Make connect to the MCP ecosystem:
- Dev Mode MCP Server: allows AI coding tools to pull design context
- Make MCP Connectors: allow Make to pull context from external tools

### Code to Canvas (February 2026)

A new bidirectional workflow:
1. Build UI with Claude Code
2. Capture the live browser state
3. Paste into Figma as an editable frame (not a screenshot -- real layers and components)
4. Collaborate, annotate, compare on the canvas
5. Pull design context back into Claude Code via MCP

This creates a loop: Code -> Figma -> Code

---

## 10. Can Make Output Be Customized/Configured?

### AI Model Selection

- Switch between Claude Sonnet 4.6 and Claude Opus 4.6 from the prompt box
- Different models behave differently in code generation and structuring
- Opus 4.6: best for complex, interactive apps (described as "best Anthropic model tested")
- Sonnet 4.6: fast, capable, preferred by users 70% over Sonnet 4.5

### Design System Configuration

- Import npm packages (public and private)
- Add `guidelines/` markdown files for component selection guidance
- Create templates with baseline configurations for team standardization
- Two template approaches: "Packages and guidelines only" or "Starter application"

### MCP Connectors

- Partner connectors: Notion, Asana, Linear, GitHub, Atlassian, Amplitude, Box, Dovetail, Granola, Marvin, zeroheight
- Custom connectors: connect to any remote MCP server including internal tools
- Admin controls: organization admins can restrict custom connector creation

### Backend Integration

- Supabase integration (open beta for all users)
- Provides: user authentication, data storage, Postgres database, private APIs, secret management
- Currently limited to basic key-value stores (not full SQL database management)
- Can connect to external APIs (OpenAI, Spotify, LinkedIn, etc.) with secure key management

### Export Options

- Download code as ZIP file
- Push directly to GitHub (creates a repo in your account)
- Publish to live web with dedicated URL or custom domain
- Copy preview snapshots as design layers into Figma Design files

---

## 11. How Does Make Handle Component Variants and Props?

### Figma Component Properties

Figma components support four property types:
1. **Text**: customizable text content
2. **Boolean**: true/false toggles (e.g., icon visibility)
3. **Instance swap**: swap nested components with alternatives
4. **Variant**: named variations (size, state, theme, etc.)

### How Make Translates These

- When libraries are connected, Make uses your actual component variants
- Component variant properties map to props in the generated React code
- Boolean properties become conditional renders
- Text properties become string props
- Variant properties become enum-like props

### Best Practices

- Reference exact component names as they appear in Figma Assets
- Connect your team library BEFORE prompting
- Make will generate prototypes using your actual button (with defined variants), spacing tokens, and UI components instead of inventing generic ones

### Limitations

- Make sometimes ignores library components and invents generic UI
- Even clean, auto-layout frames can yield misaligned results
- Rough, non-auto-layout frames produce structurally incoherent output
- Design consistency can't always be maintained despite repeated prompting

---

## 12. Code Quality Assessment

### Strengths

- Fast ideation: excellent for 10-20 rounds of quick exploration
- Non-technical users can prototype apps in hours
- Auto-generates SEO landmarks and ARIA labels
- Built-in Supabase support for data-driven prototypes
- Real-time iteration without rebuilds
- Multiple AI model options for different needs
- Built-in code editor for immediate tweaking

### Weaknesses

- **Single-file structure**: all code tends to accumulate in one file
- **Not production-ready**: serves as a starting point, not final output
- **Design fidelity issues**: fails with rough/non-auto-layout frames
- **Overwriting**: sometimes rewrites large sections unnecessarily
- **Generic output**: can produce template-like, unoriginal designs
- **Lacks UX depth**: attractive visuals but weak information architecture
- **No responsive code**: doesn't automatically handle multi-screen adaptation
- **No complex logic**: limited API calls, error handling, routing
- **Local dev issues**: running exported code locally requires significant manual config (no `package.json` included, imports resolved differently)
- **CSS divergence**: generated CSS often doesn't match library variables
- **React-only**: no framework diversity

### Realistic Expectations

- Reduces initial development time by 50-70% for teams with mature design systems
- Best used as a prototyping tool, not a production code generator
- Recommended workflow: Make for ideation -> Figma Design for precision -> code editors for production

---

## 13. Access and Pricing

| Seat Type | Capabilities |
|---|---|
| **Full seat (paid)** | Full AI features, publish/share Make files, create templates |
| **View/Collab/Dev seat** | Unlimited Make files in drafts, AI features in available products |
| **Starter plan** | Unlimited drafts, share up to 3 Make files with team |
| **Free** | Limited capabilities |

- AI toggle must be enabled by team/org admin
- Make Kits: early access (apply required)
- Private npm registry: paid plans only
- Custom MCP connectors: organization admin approval by default
- Credit-based payment system starting March 2026

---

## 14. Architecture Summary

```
                    Figma Ecosystem
                    ===============

  [Figma Design]  <--Make Kits-->  [Figma Make]
       |                               |
       | Code Connect                  | npm packages
       | (CLI / UI)                    | + guidelines
       v                               v
  [Dev Mode]                      [Generated React App]
       |                               |
       | MCP Server                    | Export
       v                               v
  [AI Coding Tools]              [GitHub / ZIP / Web]
  (Cursor, Claude Code,
   Windsurf, VS Code)

  [Code to Canvas] = Claude Code -> Figma Design (bidirectional via MCP)
```

### Data Flow

1. **Design -> Make**: Figma designs, libraries, and images feed into Make
2. **Make -> Code**: AI generates React + Tailwind CSS code
3. **Code -> Export**: ZIP download, GitHub push, or web publish
4. **External Context -> Make**: MCP connectors pull data from Amplitude, Notion, GitHub, etc.
5. **Code Connect -> MCP Server -> AI Tools**: Production code mappings feed external AI coding tools
6. **Claude Code -> Figma**: Code to Canvas brings live UI into editable Figma frames

---

## 15. Key Takeaways for VaultSpec

1. **Make is React-only**: If VaultSpec needs Svelte (per current frontend architecture), Make cannot directly generate Svelte code. However, Make's prototyping capabilities could still inform design decisions.

2. **Code Connect + MCP is the production path**: For production-quality code that uses your real design system, the recommended approach is Code Connect mappings + Figma MCP Server + an external AI coding tool (Claude Code, Cursor).

3. **Make Kits are early access**: The ability to auto-convert Figma libraries to React components is still maturing.

4. **Custom MCP connectors**: Make can connect to any remote MCP server, potentially useful for pulling VaultSpec-specific context into prototyping workflows.

5. **Design tokens flow**: Variables -> DTCG JSON -> CSS custom properties (via MCP) or CSS files (via Make Kits). The Tailwind token mapping is still a manual/semi-automated process.

6. **Code to Canvas is new**: The bidirectional Claude Code <-> Figma workflow (February 2026) is the latest evolution, enabling a design-code-design loop.

---

## Sources

- [Figma Make GA Blog Post](https://www.figma.com/blog/figma-make-general-availability/)
- [Config 2025 Recap](https://www.figma.com/blog/config-2025-recap/)
- [Schema 2025 Design Systems Recap](https://www.figma.com/blog/schema-2025-design-systems-recap/)
- [Explore Figma Make - Help Center](https://help.figma.com/hc/en-us/articles/31304412302231-Explore-Figma-Make)
- [Beyond the Basics: Using Figma Make](https://help.figma.com/hc/en-us/articles/35710574222487-Beyond-the-basics-Using-Figma-Make)
- [Bring Your Design System Package - Developer Docs](https://developers.figma.com/docs/code/bring-your-design-system-package/)
- [Use Packages and Third-Party Libraries](https://developers.figma.com/docs/code/use-packages-and-third-party-libraries/)
- [Use Your Design System Package in Make](https://help.figma.com/hc/en-us/articles/35946832653975-Use-your-design-system-package-in-Figma-Make)
- [Working with React - Developer Docs](https://developers.figma.com/docs/code/working-with-react/)
- [Code Connect - Help Center](https://help.figma.com/hc/en-us/articles/23920389749655-Code-Connect)
- [Code Connect - Developer Docs](https://developers.figma.com/docs/code-connect/)
- [Code Connect MCP Integration](https://developers.figma.com/docs/figma-mcp-server/code-connect-integration/)
- [Select AI Model in Make](https://help.figma.com/hc/en-us/articles/36400680326551-Select-an-AI-model-to-use-in-Figma-Make)
- [Figma Make MCP Connectors](https://www.cmswire.com/digital-experience/figma-make-adds-custom-model-context-protocol-6-new-connectors/)
- [Partner MCP Connectors - Help Center](https://help.figma.com/hc/en-us/articles/35440096186007-Use-verified-partner-MCP-connectors-in-Figma-Make)
- [Custom MCP Connectors - Help Center](https://help.figma.com/hc/en-us/articles/38147204302743-Create-and-use-custom-MCP-connectors-in-Figma-Make)
- [Add Backend to Make - Help Center](https://help.figma.com/hc/en-us/articles/32640822050199-Add-a-backend-to-a-functional-prototype-or-web-app)
- [Code to Canvas - Figma Blog](https://www.figma.com/blog/introducing-claude-code-to-figma/)
- [Figma Make Review - Cybernews](https://cybernews.com/ai-tools/figma-make-review/)
- [Figma MCP Server Tested](https://research.aimultiple.com/figma-to-code/)
- [Figma Make Won't Work Until You Do This](https://learn.thedesignsystem.guide/p/figma-make-wont-work-until-you-do)
- [How to Get Your Design System into Figma Make](https://finchy.medium.com/how-to-get-your-design-system-into-figma-make-3ac735205e7f)
- [Guide to Dev Mode](https://help.figma.com/hc/en-us/articles/15023124644247-Guide-to-Dev-Mode)
- [Introducing Figma's Dev Mode MCP Server](https://www.figma.com/blog/introducing-figmas-dev-mode-mcp-server/)
- [Figma Make - Official Page](https://www.figma.com/make/)
- [Supabase + Figma Make Blog](https://supabase.com/blog/figma-make-support-for-supabase)
