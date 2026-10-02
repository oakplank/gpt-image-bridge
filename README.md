# gpt-image-bridge

Generate images with OpenAI's **GPT Image 2.5** from a CLI coding agent by bridging through the [`codex` CLI](https://github.com/openai/codex). Uses your ChatGPT subscription — **no API key required, no per-image billing.**

The bridge is a standalone bash script — [Claude Code](https://docs.claude.com/en/docs/claude-code), Cursor, Gemini CLI, aider, or any other agent that can run a shell command can call it. Claude Code just gets the nicest ergonomics, because the included installer registers it as a skill so Claude reaches for it unprompted.

Works with any design skill (like the [`image-taste-frontend`](https://github.com/Leonxlnx/taste-skill) skill from [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)) or on its own whenever your agent needs to produce a picture.

## What it is

This adds image generation to coding agents through a thin bash wrapper that shells out to `codex exec`, calls its `image_generation` tool using your existing ChatGPT authentication, and copies the PNG where you asked. Your agent then reads the PNG back into context.

OpenAI's [Images 2.5 announcement](https://openai.com/index/introducing-chatgpt-images-2-5/) includes availability in Codex. The bridge uses the image model provided by Codex; it does not select or verify a particular backend model. The executable is still named `gpt-image-2` for compatibility with existing installs and scripts. That filename does not pin generation to GPT Image 2.

```
your agent ──shell──▶ gpt-image-2 wrapper ──codex exec──▶ image_generation
                              │                                  │
             read PNG ◀── copies to your ◀──── out.png in a ◀────┘
                          output path          private temp dir
```

Codex runs sandboxed and can only write inside its own working directory, so the wrapper points it at a private temp dir and performs the final copy itself. That keeps arbitrary output paths (and Windows paths) working reliably.

## Prerequisites

- Any coding agent that can run shell commands — [Claude Code](https://docs.claude.com/en/docs/claude-code), Cursor, Gemini CLI, aider, or your own script
- [`codex` CLI](https://github.com/openai/codex) installed (`brew install codex` on macOS, `npm install -g @openai/codex` anywhere)
- A ChatGPT subscription (Plus / Pro / Team) logged in via `codex login`
- macOS, Linux, or Windows — the wrapper is bash, which on Windows runs under Git Bash (the shell Claude Code already uses there) or WSL

Verify:

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
To generate an image, run: gpt-image-2 "<detailed prompt>" <absolute-output-path.png> [--size WxH] [--ref <image>]...
Prompts should be dense and art-directed. Calls take 4-6 minutes, so allow a long timeout.
Read the PNG back afterward to check the result.
```

[`skills/gpt-image-bridge/SKILL.md`](./skills/gpt-image-bridge/SKILL.md) is the full version of those instructions if your agent supports a longer brief. It's phrased for Claude Code, but the substance — prompt density, when to use it, when not to, timeout handling — applies anywhere.

### Agent install (paste this to your agent)

Drop the block below into your Claude Code session (or any shell-capable AI agent) and it will install the skill for you, verify prereqs, and offer a smoke test.

```
Please install the gpt-image-bridge skill from https://github.com/oakplank/gpt-image-bridge so I can generate images with GPT Image 2.5 through Codex and my ChatGPT subscription.

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
- `--ref <image>` — attach a reference image, like uploading one in ChatGPT. Repeat it for several references. See [Reference images](#reference-images) below.

On success the wrapper prints the absolute output path. On failure it prints the tail of the codex log to stderr.

## Reference images

Attach an image with `--ref` and the model sees its actual pixels, the same as uploading an image in ChatGPT. Use it to:

- **Edit an image:** change one thing and keep everything else.
- **Keep a subject consistent:** put the same person, product, logo, or mascot into a new scene.
- **Match a style:** give it a screenshot, mood board, or brand visual and copy the look.
- **Refine a result:** pass a generated image back in and ask for changes instead of starting over.

### Example

| Reference (`--ref`) | Result |
| --- | --- |
| ![Red balloon on a blue sky](docs/ref-example-before.jpg) | ![The same image with the balloon recolored green](docs/ref-example-after.jpg) |

```bash
gpt-image-2 \
  "Recreate this exact image, changing only the balloon color to green. Keep the framing, balloon position and size, the highlight, the ribbon curve, and every cloud exactly where they are." \
  /tmp/green-balloon.png \
  --ref /tmp/red-balloon.png
```

Only the color changed. The balloon, highlight, ribbon, and clouds stayed within about 1% of their original positions.

### Asking your agent

You don't need the flag syntax. Name the file in plain language and the agent passes it with `--ref`:

- "Use ~/Desktop/me.jpg as a reference and put me on a beach at sunset."
- "Edit ~/Downloads/logo.png: make the background dark navy, keep the logo exactly the same."
- "Make a hero image of the bottle in ~/shots/bottle.png on a marble counter, in the style of ~/moodboard/style.jpg."

### More command examples

```bash
# Two references: a subject and a style
gpt-image-2 "the bottle from the first image, photographed in the style of the second image" \
  /tmp/hero.png --ref ~/shots/bottle.png --ref ~/moodboard/style.jpg

# An edit that keeps the reference's dimensions (here 1024x1536)
gpt-image-2 "the same portrait, change only the jacket to red; keep the face, pose, and background identical" \
  /tmp/red-jacket.png --ref ~/photos/portrait.png --size 1024x1536
```

### Tips

- **For edits, say what must stay the same:** "change only X; keep Y and Z exactly as they are." Without that, the model treats the reference as loose inspiration.
- **Pass `--size` when dimensions matter.** The output size can differ from the reference: a 1024×1024 reference came back 1254×1254.
- **With several references, say what each one is for** ("the first image is the product, the second is the style"). They are attached in the order you pass them.
- **Paths can be relative or absolute.** A missing file stops the wrapper with an error before any quota is used.
- **iPhone photos:** codex may not read HEIC. Convert first, e.g. `sips -s format png photo.heic --out photo.png` on macOS.

### Limits

- The model regenerates the whole image, so expect small drift even in the parts you asked to keep. For exact mechanical edits (crop, resize, format conversion, exact hex colors), use an image tool such as ImageMagick.
- A call with references uses ChatGPT quota, the same as a normal generation.

## Why go through codex instead of calling the API directly?

| | Through codex | Direct OpenAI API |
| --- | --- | --- |
| Auth | Your ChatGPT subscription | Requires API key |
| Cost | Uses ChatGPT message quota | Per-image billing |
| Speed | Slower (codex reasons before calling the image tool) | Faster |
| Prompt quality | Your configured Codex model refines the prompt before generating | Passed verbatim |

If you already pay for ChatGPT, the codex route is free at the margin. If you'd rather pay per image for speed, call the [Images API](https://platform.openai.com/docs/api-reference/images) directly — this bridge is for the subscription route.

## Pair with a design skill

This bridge is just the tool — it gives your agent access to Codex's image generation, not the taste to know what a good image looks like. For art-directed frontend work, stack it under a design-taste skill:

- [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) by [@lexnlin](https://x.com/lexnlin) — high-agency frontend, anti-slop. The `image-taste-frontend` skill inside it is the one this bridge was originally built to feed.
- Any other skill that follows an "image first, then code" workflow

Install one alongside `gpt-image-bridge` and it'll automatically use the wrapper for its image-generation steps:

```bash
npx skills add https://github.com/Leonxlnx/taste-skill --skill image-taste-frontend -a claude-code
```

## Caveats

- **Latency**: calls go through codex's reasoning loop before the image tool fires — expect 4–6 minutes per image. Latency depends on your codex `reasoning_effort` config.
- **Quota**: ChatGPT subscriptions have message limits. Heavy automated use can hit rate caps.
- **Terms of service**: using `codex` programmatically to drive image generation is within the spirit of the tool (codex is an official OpenAI product), but consumer-subscription automation is ultimately gated by OpenAI's terms. Use at your own risk.
- **Bash required** — native on macOS/Linux; on Windows use Git Bash (bundled with Git for Windows, and what Claude Code uses there) or WSL.

## License

MIT — see [LICENSE](./LICENSE).
