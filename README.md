# gpt-image-bridge

Generate images with OpenAI's `gpt-image-2` from a CLI coding agent by bridging through the [`codex` CLI](https://github.com/openai/codex). Uses your ChatGPT subscription — **no API key required, no per-image billing.**

The bridge is a standalone bash script — [Claude Code](https://docs.claude.com/en/docs/claude-code), Cursor, Gemini CLI, aider, or any other agent that can run a shell command can call it. Claude Code just gets the nicest ergonomics, because the included installer registers it as a skill so Claude reaches for it unprompted.

Works with any design skill (like the [`image-taste-frontend`](https://github.com/Leonxlnx/taste-skill) skill from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)) or on its own whenever your agent needs to produce a picture.

## What it is

Coding agents don't ship with an image generation tool. This adds a thin bash wrapper that shells out to `codex exec`, which calls `gpt-image-2` using your existing ChatGPT authentication and copies the PNG where you asked. Your agent then reads the PNG back into context.

```
your agent ──shell──▶ gpt-image-2 wrapper ──codex exec──▶ gpt-image-2 (OpenAI)
                              │                                  │
             read PNG ◀── copies to your ◀──── out.png in a ◀────┘
                          output path          private temp dir
```

Codex runs sandboxed and can only write inside its own working directory, so the wrapper points it at a private temp dir and performs the final copy itself. That keeps arbitrary output paths (and Windows paths) working reliably.

## Prerequisites

- Any coding agent that can run shell commands — [Claude Code](https://docs.claude.com/en/docs/claude-code), Cursor, Gemini CLI, aider, or your own script
- macOS, Linux, or Windows — the wrapper is bash, which on Windows runs under Git Bash (the shell Claude Code already uses there) or WSL
- One generation backend:
  - Default Codex route: [`codex` CLI](https://github.com/openai/codex), a ChatGPT subscription, and `codex login`
  - Optional Atlas Cloud route: Python 3 and `ATLASCLOUD_API_KEY`

Verify the default Codex route:

```bash
codex login status   # should say: Logged in using ChatGPT
codex features list | grep image_generation    # should be: stable true
```

## Install

### Claude Code

```bash
git clone https://github.com/oakplank/gpt-image-bridge.git
cd gpt-image-bridge
./install.sh
```

The installer copies the skill into `~/.claude/skills/gpt-image-bridge/` and makes the wrapper executable. Claude Code picks up skills in that directory automatically — no further config needed, and Claude will invoke the wrapper on its own when you ask for an image.

### Any other agent

There's nothing to install — the wrapper is a self-contained bash script with no dependencies beyond `codex`. Clone the repo, make it executable, and put it somewhere on your `PATH`:

```bash
git clone https://github.com/oakplank/gpt-image-bridge.git
chmod +x gpt-image-bridge/skills/gpt-image-bridge/bin/gpt-image-2
ln -s "$PWD/gpt-image-bridge/skills/gpt-image-bridge/bin/gpt-image-2" /usr/local/bin/gpt-image-2
```

(On Windows, skip the symlink and call the script by its full path, or add its directory to `PATH`.)

Then tell your agent it exists. Most agents take a rules or instructions file — `.cursorrules`, `AGENTS.md`, `GEMINI.md`, a system prompt — and a couple of lines is enough:

```
To generate an image, run: gpt-image-2 "<detailed prompt>" <absolute-output-path.png> [--size WxH]
Prompts should be dense and art-directed. Calls take 4-6 minutes, so allow a long timeout.
Read the PNG back afterward to check the result.
```

[`skills/gpt-image-bridge/SKILL.md`](./skills/gpt-image-bridge/SKILL.md) is the full version of those instructions if your agent supports a longer brief. It's phrased for Claude Code, but the substance — prompt density, when to use it, when not to, timeout handling — applies anywhere.

### Agent install (paste this to your agent)

Drop the block below into your Claude Code session (or any shell-capable AI agent) and it will install the skill for you, verify prereqs, and offer a smoke test.

```
Please install the gpt-image-bridge skill from https://github.com/oakplank/gpt-image-bridge so I can generate images with gpt-image-2 through my ChatGPT subscription.

1. Check that the `codex` CLI is installed and logged in:
     codex login status
   It should say "Logged in using ChatGPT". If codex is missing or not logged in, stop and tell me to run `brew install codex && codex login` first.

2. Clone and install:
     git clone https://github.com/oakplank/gpt-image-bridge.git /tmp/gpt-image-bridge
     cd /tmp/gpt-image-bridge && ./install.sh

3. Verify ~/.claude/skills/gpt-image-bridge/bin/gpt-image-2 exists and is executable.

4. Once installed, offer to smoke-test by generating a small image to /tmp/test.png and opening it so I can confirm it works end-to-end. Use the maximum Bash timeout (600000 ms) — codex reasons before the image tool fires and calls routinely take 4-6 minutes.

Report back when each step is done, and stop if any step fails.
```

## Usage

Once your agent knows about the wrapper it will invoke it whenever you ask for an image. You can also call it directly:

```bash
gpt-image-2 \
  "a photorealistic hummingbird hovering in front of a red desert canyon at golden hour, shallow depth of field, magazine quality" \
  /tmp/hummingbird.png
```

If you installed via `install.sh` and didn't symlink it onto your `PATH`, the wrapper lives at `~/.claude/skills/gpt-image-bridge/bin/gpt-image-2`.

Optional flags:

- `--size WxH` — request a specific aspect ratio (e.g. `--size 1792x1024`). If omitted, the model picks its own dimensions.
- `--provider codex|atlas` — keep the subscription-backed Codex route (default), or call GPT Image 2 through Atlas Cloud.
- `--quality low|medium|high` — set Atlas Cloud output quality (default: `medium`).

### Optional Atlas Cloud backend

Use Atlas Cloud when you prefer a direct API request over the slower Codex reasoning loop. The default remains `codex`, so existing installs and commands do not change.

```bash
export ATLASCLOUD_API_KEY="your-api-key"

gpt-image-2 \
  "a photorealistic hummingbird hovering in front of a red desert canyon at golden hour" \
  /tmp/hummingbird.png \
  --provider atlas \
  --size 1536x1024 \
  --quality high
```

The Atlas route uses `openai/gpt-image-2/text-to-image`. It submits the generation request once, polls the prediction with bounded retries, and downloads the resulting PNG atomically. It requires Python 3 and incurs Atlas Cloud API usage charges.

On success the wrapper prints the absolute output path. Codex failures print the tail of the Codex log; Atlas failures print the API or polling error to stderr.

## Why go through codex instead of calling the API directly?

| | Through codex | Atlas Cloud backend | Direct OpenAI API |
| --- | --- | --- | --- |
| Auth | Your ChatGPT subscription | `ATLASCLOUD_API_KEY` | Requires OpenAI API key |
| Cost | Uses ChatGPT message quota | Per-image Atlas billing | Per-image OpenAI billing |
| Speed | Slower (codex reasons before calling the image tool) | Direct API request | Direct API request |
| Prompt quality | codex refines your prompt before generating | Passed verbatim | Passed verbatim |

If you already pay for ChatGPT, the codex route is free at the margin. If you'd rather pay per image for speed, call the [Images API](https://platform.openai.com/docs/api-reference/images) directly — this bridge is for the subscription route.

## Pair with a design skill

This bridge is just the tool — it gives your agent the ability to call `gpt-image-2`, not the taste to know what a good image looks like. For art-directed frontend work, stack it under a design-taste skill:

- [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) by [@lexnlin](https://x.com/lexnlin) — high-agency frontend, anti-slop. The `image-taste-frontend` skill inside it is the one this bridge was originally built to feed.
- Any other skill that follows an "image first, then code" workflow

Install one alongside `gpt-image-bridge` and it'll automatically use the wrapper for its image-generation steps:

```bash
npx skills add https://github.com/Leonxlnx/taste-skill --skill image-taste-frontend -a claude-code
```

## Caveats

- **Latency**: the default Codex route goes through a reasoning loop before the image tool fires — expect 4–6 minutes per image. Latency depends on your codex `reasoning_effort` config.
- **Quota**: ChatGPT subscriptions have message limits. Heavy automated use can hit rate caps.
- **Terms of service**: using `codex` programmatically to drive image generation is within the spirit of the tool (codex is an official OpenAI product), but consumer-subscription automation is ultimately gated by OpenAI's terms. Use at your own risk.
- **Bash required** — native on macOS/Linux; on Windows use Git Bash (bundled with Git for Windows, and what Claude Code uses there) or WSL.

## License

MIT — see [LICENSE](./LICENSE).
