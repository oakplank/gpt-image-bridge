---
name: gpt-image-bridge
description: Use when the user asks for an image, mockup, logo, avatar, hero image, illustration, diagram, visual reference, or any generated picture, or when a design skill needs an image produced. Bridges to OpenAI's gpt-image-2 through the codex CLI using a ChatGPT subscription, with Atlas Cloud as an optional direct API provider.
---

# gpt-image-bridge

Claude Code has no native image generation tool. This skill bridges that gap by shelling out to the `codex` CLI, which calls OpenAI's `gpt-image-2` model under the hood. Codex is authenticated via the user's ChatGPT subscription, so no API key is required.

## When to use

Invoke the wrapper any time the user wants an image produced. Examples:

- "Generate a hero image for..."
- "Make me a mockup of..."
- "I need an avatar / logo / illustration / diagram of..."
- "Show me what X would look like"
- A design-taste skill (e.g. `image-taste-frontend` from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)) is driving an image-first workflow and needs an image generated

Do **not** invoke it for:

- Small programmatic PNGs (1px dots, solid-color placeholders, charts) — write those directly with a few lines of Python.
- Editing an existing image pixel-by-pixel.

## How to call it

```bash
~/.claude/skills/gpt-image-bridge/bin/gpt-image-2 "<prompt>" <absolute-output-path.png> [--size WxH] [--provider codex|atlas]
```

- **Prompt** should be dense and art-directed: composition, lighting, camera/lens, mood, style reference. Terse prompts produce generic output.
- **Output path** must be absolute. `/tmp/` works for throwaways; a project-local `design/` directory for kept assets.
- **Size is optional** — if omitted, the model chooses its own dimensions. Only pass `--size` when the user specifies one or the layout requires a particular aspect ratio.
- **Provider is optional** — use `codex` by default. Use `atlas` only when `ATLASCLOUD_API_KEY` is configured and the user accepts per-image API billing.
- **Atlas quality is optional** — pass `--quality low|medium|high`; the default is `medium`.
- Codex calls routinely take 4–6 minutes (codex reasons before calling the image tool; exact latency depends on the user's codex `reasoning_effort` config). Set the `Bash` tool timeout to the **maximum, 600000 ms**, or run it in the background and poll.
- The wrapper prints the absolute output path to stdout on success, or a tail of the codex log to stderr on failure.

After the wrapper returns, `Read` the PNG back into context so you can analyze it before coding or responding.

## Under the hood

The wrapper runs:

```
codex exec --skip-git-repo-check -s workspace-write -C <private-temp-dir> "<augmented prompt>"
```

with explicit instructions to use the `image_generation` tool (not fabricate a PNG in Python — codex will try that if you let it). Codex saves the PNG as `out.png` inside the private temp dir — the only place its sandbox is guaranteed to allow writes — and the wrapper copies it to the requested output path. Codex never handles the final path, so sandbox denials and Windows/POSIX path mismatches can't occur, and the previous output file is only overwritten once a new image actually exists.

With `--provider atlas`, the wrapper calls `openai/gpt-image-2/text-to-image` through Atlas Cloud. The helper makes exactly one generation POST, performs bounded GET polling, downloads the completed PNG, and atomically replaces the destination. Never automatically retry the generation POST.

## Prerequisites (user-side)

- `codex` CLI installed (`brew install codex` on macOS, `npm install -g @openai/codex` anywhere)
- `codex login status` reports "Logged in using ChatGPT" (ChatGPT Plus/Pro/Team subscription)
- `image_generation` feature enabled — on by default (`codex features list | grep image_generation`)
- macOS, Linux, or Windows (runs under Git Bash — the shell Claude Code already uses on Windows — or WSL)

For the optional Atlas Cloud route, configure `ATLASCLOUD_API_KEY` and ensure Python 3 is installed. Do not select this provider without warning the user that it incurs API usage charges.

If the wrapper errors with "codex CLI not found", tell the user to run `brew install codex && codex login` (or `npm install -g @openai/codex`).

## Cost

- **The default Codex route has no OpenAI API spend.** Calls consume the user's ChatGPT message quota, not billed credits.
- Still rate-limited by the ChatGPT plan, so don't burn quota on throwaways.
- **Atlas Cloud is billed separately.** Only `--provider atlas` uses Atlas credits; the default Codex route is unchanged.
