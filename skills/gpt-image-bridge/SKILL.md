---
name: gpt-image-bridge
description: Use when the user asks for an image, mockup, logo, avatar, hero image, illustration, diagram, visual reference, or any generated picture, or when a design skill needs an image produced. Bridges to OpenAI's GPT Image 2.5 through the codex CLI using a ChatGPT subscription — no API key.
---

# gpt-image-bridge

This skill adds image generation to Claude Code by shelling out to the `codex` CLI and its `image_generation` tool. OpenAI's [Images 2.5 announcement](https://openai.com/index/introducing-chatgpt-images-2-5/) includes availability in Codex. Codex is authenticated via the user's ChatGPT subscription, so no API key is required.

The bridge uses the image model provided by Codex; it does not select or verify a particular backend model. The executable name `gpt-image-2` is retained for compatibility and does not pin the model to GPT Image 2. Do not pass an image-model ID to `codex --model`: that option selects the coding model, not the image backend.

## When to use

Invoke the wrapper any time the user wants an image produced. Examples:

- "Generate a hero image for..."
- "Make me a mockup of..."
- "I need an avatar / logo / illustration / diagram of..."
- "Show me what X would look like"
- "Use this photo / logo / screenshot as a reference..." or "Edit this image so that..." — pass the file with `--ref`
- A design-taste skill (e.g. `image-taste-frontend` from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)) is driving an image-first workflow and needs an image generated

Do **not** invoke it for:

- Small programmatic PNGs (1px dots, solid-color placeholders, charts) — write those directly with a few lines of Python.
- Exact mechanical edits (crop, resize, convert, recolor to an exact hex) — use Python or ImageMagick. A `--ref` edit regenerates the whole image, so expect small drift.

## How to call it

```bash
~/.claude/skills/gpt-image-bridge/bin/gpt-image-2 "<prompt>" <absolute-output-path.png> [--size WxH] [--ref <image>]...
```

- **Prompt** should be dense and art-directed: composition, lighting, camera/lens, mood, style reference. Terse prompts produce generic output.
- **Output path** must be absolute. `/tmp/` works for throwaways; a project-local `design/` directory for kept assets.
- **Size is optional** — if omitted, the model chooses its own dimensions. Only pass `--size` when the user specifies one or the layout requires a particular aspect ratio.
- **`--ref <image>`** attaches a reference image, the same as uploading one in ChatGPT. Repeat it for several. Codex's image tool sees the actual pixels, so it works for edits and for carrying a face, product, or style into a new scene. For edits, state the invariants in the prompt: "change only X; keep the framing, Y and Z exactly as they are." The output size can differ from the reference (a 1024×1024 reference came back 1254×1254), so pass a matching `--size` when dimensions must be preserved.
- Calls routinely take 4–6 minutes (codex reasons before calling the image tool; exact latency depends on the user's codex `reasoning_effort` config). Set the `Bash` tool timeout to the **maximum, 600000 ms**, or run it in the background and poll.
- The wrapper prints the absolute output path to stdout on success, or a tail of the codex log to stderr on failure.

After the wrapper returns, `Read` the PNG back into context so you can analyze it before coding or responding.

## Under the hood

The wrapper runs:

```
codex exec --skip-git-repo-check -s workspace-write -C <private-temp-dir> [--image=<ref>...] "<augmented prompt>"
```

with explicit instructions to use the `image_generation` tool (not fabricate a PNG in Python — codex will try that if you let it). Codex saves the PNG as `out.png` inside the private temp dir — the only place its sandbox is guaranteed to allow writes — and the wrapper copies it to the requested output path. Codex never handles the final path, so sandbox denials and Windows/POSIX path mismatches can't occur, and the previous output file is only overwritten once a new image actually exists.

## Prerequisites (user-side)

- `codex` CLI installed (`brew install codex` on macOS, `npm install -g @openai/codex` anywhere)
- `codex login status` reports "Logged in using ChatGPT" (ChatGPT Plus/Pro/Team subscription)
- `image_generation` feature enabled — on by default (`codex features list | grep image_generation`)
- macOS, Linux, or Windows (runs under Git Bash — the shell Claude Code already uses on Windows — or WSL)

If the wrapper errors with "codex CLI not found", tell the user to run `brew install codex && codex login` (or `npm install -g @openai/codex`).

## Cost

- **No OpenAI API spend.** Calls consume the user's ChatGPT message quota, not billed credits.
- Still rate-limited by the ChatGPT plan, so don't burn quota on throwaways.
