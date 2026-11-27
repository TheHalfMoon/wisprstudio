# WisprStudio — License Notice

## Abbreviation

AGPL-3.0-only

## Notice

Copyright 2024-present Palash Debnath (`Debpalash`) and VoiceStudio contributors.
Copyright 2026 Wispral Contributors.

WisprStudio is **free and open-source software, licensed strictly under the GNU
Affero General Public License, Version 3 (`AGPL-3.0-only`)**. You are free to use,
copy, modify, and redistribute it under the terms of the AGPL-3.0, including
commercial and internal business use of the application itself. Model weights,
tokenizers, and other third-party assets retain their own terms; this application
license does not grant or summarize rights under those separate terms.

Because this is the **Affero** GPL, if you modify WisprStudio and make that
modified version available to others over a network, you must also offer those
users the complete corresponding source code of your modified version under these
same AGPL-3.0 terms. See the full text in [`LICENSE`](LICENSE) and attributions
in [`NOTICE`](NOTICE).

### Complete Corresponding Source Code Offer

The complete corresponding source code for WisprStudio is available at:
<https://github.com/TheHalfMoon/wisprstudio>

(This Notice is a plain-language summary; the binding terms are the full GNU
AGPL-3.0 text in [`LICENSE`](LICENSE).)

### Scope & Upstream Attributions

These terms cover the WisprStudio application — the Electron desktop and web
app (`electron/`), its native desktop helper (`native/`), the FastAPI backend
(`backend/`), and supporting build / packaging files (`scripts/`, `deploy/`,
`.github/`). Upstream VoiceStudio code by Palash Debnath (`Debpalash`) and
contributors (<https://github.com/debpalash/VoiceStudio>) remains attributed under
`AGPL-3.0-only`. Electron components adapted from T3 Code keep their MIT notice in
`electron/T3CODE-LICENSE.txt`.

The bundled `omnivoice/` Python package — the underlying TTS model code by Han Zhu
(<https://github.com/k2-fsa/OmniVoice>) — is **separately licensed under Apache
License 2.0** by its upstream authors and is not relicensed here. Apache License 2.0
is compatible with, and may be combined under, the GNU AGPL-3.0. See `pyproject.toml`.

Downloaded model weights are not relicensed by WisprStudio. The upstream
`k2-fsa/OmniVoice` model card identifies its code as Apache-2.0 and pretrained
weights as CC-BY-NC. Its `audio_tokenizer/LICENSE` contains separate Boson
Higgs Audio 2 and Meta Llama community terms. Commercially permissive local TTS
engines (`Kokoro-82M` under Apache-2.0 and `Piper` under MIT) are recommended by
default for commercial workflows; non-commercial model weights are explicitly
labeled in catalog metadata.

The maintained About panel displays selected model credits and required literal
Higgs Audio and Llama attribution text, along with the AGPL-3.0 source-code offer.
See [model credit sources](docs/model-credits.md) for evidence and remaining gaps.

The [model licence records](backend/config/model_licenses.json) distinguish
inspected non-commercial terms from unreviewed upstream metadata. A false
commercial-use flag includes unresolved review; it is not a claim that every
listed model forbids commercial use.

Third-party dependencies retain their own licenses. See `bun.lock`, `uv.lock`,
and `native/desktop-bridge/Cargo.lock` for the resolved set.

The locked PyAV 15.1.0 wheels bundle FFmpeg and x264/x265 libraries. PyAV's source
licence alone does not describe those binaries' terms. The
[wheel audit](docs/licensing/pyav-15.1.0-audit.md) records their hashes, build flags,
upstream licence-label patch, and unresolved redistribution requirements.

### Reference

The full canonical text of the GNU Affero General Public License, Version 3 is
reproduced verbatim in [`LICENSE`](LICENSE). The authoritative copy lives at
<https://www.gnu.org/licenses/agpl-3.0.txt>.
