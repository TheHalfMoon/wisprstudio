<div align="center">
  <h1><sub><img src="../../docs/logo.png" alt="" width="36" height="36" /></sub> WisprStudio</h1>
  <p>
    <strong>🎉 <a href="https://github.com/TheHalfMoon/wisprstudio/stargazers">GitHub Star 突破 10 萬，感謝大家！</a></strong>
  </p>
  <h2>AI 語音工作室，就在你的裝置上。</h2>
  <h3>支援 646 種語言的聲音克隆、聲音設計、配音、聽寫、轉錄與有聲朗讀。</h3>
  <p>可在你的膝上型電腦、桌上型電腦、伺服器、手機、平板電腦等裝置上執行</p>
  <p>
    <a href="https://github.com/TheHalfMoon/wisprstudio">官網</a> ·
    <a href="https://github.com/TheHalfMoon/wisprstudio/releases/latest">下載</a> ·
    <a href="#開始使用">快速上手</a> ·
    <a href="#文件">文件</a> ·
    <a href="https://github.com/TheHalfMoon/wisprstudio">WisprStudio Pro</a> ·
    <a href="https://github.com/TheHalfMoon/wisprstudio">WisprStudio Cloud</a>
  </p>
  <!-- README_LANGUAGES_START -->
  <a id="readme-languages"></a>
  <p><sub>
    <a href="../../README.md" lang="en">🇬🇧 English</a> · <a href="README_CN.md" lang="zh-CN">🇨🇳 简体中文</a> · <a href="README_JA.md" lang="ja">🇯🇵 日本語</a> · <a href="README_KO.md" lang="ko">🇰🇷 한국어</a> · <a href="README_RU.md" lang="ru">🇷🇺 Русский</a> · <a href="README_AR.md" lang="ar">🇸🇦 العربية</a> · <a href="README_DE.md" lang="de">🇩🇪 Deutsch</a> · <a href="README_ES.md" lang="es">🇪🇸 Español</a> · <a href="README_FR.md" lang="fr">🇫🇷 Français</a> · <a href="README_HI.md" lang="hi">🇮🇳 हिन्दी</a><br />
    <a href="README_ID.md" lang="id">🇮🇩 Bahasa Indonesia</a> · <a href="README_IT.md" lang="it">🇮🇹 Italiano</a> · <a href="README_NL.md" lang="nl">🇳🇱 Nederlands</a> · <a href="README_PL.md" lang="pl">🇵🇱 Polski</a> · <a href="README_PT.md" lang="pt">🇵🇹 Português</a> · <a href="README_TH.md" lang="th">🇹🇭 ไทย</a> · <a href="README_TR.md" lang="tr">🇹🇷 Türkçe</a> · <strong lang="zh-TW">🇹🇼 繁體中文</strong> · <a href="README_UK.md" lang="uk">🇺🇦 Українська</a> · <a href="README_VI.md" lang="vi">🇻🇳 Tiếng Việt</a>
  </sub></p>
  <!-- README_LANGUAGES_END -->

  <p>
    <a href="https://github.com/TheHalfMoon/wisprstudio/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/TheHalfMoon/wisprstudio/ci.yml?branch=main&amp;style=flat-square&amp;label=build&amp;labelColor=27272a" alt="CI 構建狀態" /></a>
    <a href="https://github.com/TheHalfMoon/wisprstudio/releases/latest"><img src="https://img.shields.io/github/v/release/TheHalfMoon/wisprstudio?style=flat-square&amp;labelColor=27272a&amp;color=52525b" alt="最新版本" /></a>
    <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-52525b?style=flat-square&amp;labelColor=27272a" alt="AGPL-3.0 許可證" /></a>
    <a href="https://discord.gg/bzQavDfVV9"><img src="https://img.shields.io/badge/Discord-Join%20the%20community-5865F2?style=flat-square&amp;logo=discord&amp;logoColor=white" alt="Join Discord" /></a>
  </p>
</div>

<p align="center">
  <a href="../../docs/media/electron/voicestudio.mp4">
    <picture>
      <source media="(prefers-reduced-motion: reduce) and (max-width: 768px)" srcset="../../docs/media/electron/voice-cloning.webp" />
      <source media="(prefers-reduced-motion: reduce)" srcset="../../docs/media/electron/voice-cloning.png" />
      <img src="../../docs/media/electron/voicestudio.gif" alt="應用導覽：聲音克隆、聲音設計、配音和模型管理" width="100%" />
    </picture>
  </a><br />
  <sub>演示工作區 · 預設深色主題 · <a href="../../docs/media/electron/voicestudio.mp4">觀看高畫質演示</a></sub>
</p>

<p align="center">
  <a href="https://github.com/TheHalfMoon/wisprstudio/releases/latest"><img src="https://img.shields.io/badge/%E4%B8%8B%E8%BC%89-993f61?style=for-the-badge&amp;logo=github&amp;logoColor=ffffff" alt="下載" height="24" /></a>
  <a href="#開始使用"><img src="https://img.shields.io/badge/%E5%BF%AB%E9%80%9F%E9%96%8B%E5%A7%8B-27272a?style=for-the-badge" alt="快速上手" height="24" /></a>
</p>

<a id="what-you-can-do"></a>

## 你可以做什麼

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="../../docs/media/electron/voice-cloning.png"><img src="../../docs/media/electron/voice-cloning.webp" alt="使用內建演示聲音的聲音克隆工作區" width="100%" /></a><br />
      <strong><a href="../../docs/audio-quality.md">聲音克隆</a></strong><br />
      用一段清晰的參考錄音，生成熟悉聲音的語音。
    </td>
    <td width="50%" valign="top">
      <a href="../../docs/media/electron/dubbing.png"><img src="../../docs/media/electron/dubbing.webp" alt="影片配音工作區" width="100%" /></a><br />
      <strong><a href="../../docs/electron-dubbing.md">影片配音</a></strong><br />
      翻譯並配音影片，讓語音與原片時間對齊。
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="../../docs/media/electron/voice-design.png"><img src="../../docs/media/electron/voice-design.webp" alt="在聲音設計工作區中描述聲音" width="100%" /></a><br />
      <strong><a href="../../docs/electron-voice-design.md">聲音設計</a></strong><br />
      用文字描述你想要的聲音，然後生成。
    </td>
    <td width="50%" valign="top">
      <a href="../../docs/media/electron/models.png"><img src="../../docs/media/electron/models.webp" alt="安裝和管理本地語音模型" width="100%" /></a><br />
      <strong><a href="../../docs/downloading-models.md">本地模型</a></strong><br />
      自由選擇引擎，只下載你需要的模型。
    </td>
  </tr>
</table>

<details>
<summary><strong>更多截圖</strong></summary>

<table>
  <tr>
    <td width="50%"><a href="../../docs/media/electron/overview.png"><img src="../../docs/media/electron/overview.webp" alt="工作區概覽" width="100%" /></a><br /><strong>工作區概覽</strong></td>
    <td width="50%"><a href="../../docs/media/electron/model-packs.png"><img src="../../docs/media/electron/model-packs.webp" alt="模型組合" width="100%" /></a><br /><strong>模型組合</strong></td>
  </tr>
</table>

</details>

- **聽寫與轉錄** — 懸浮聽寫視窗與本地轉錄
- **朗讀與批次處理** — 故事、有聲書與排隊任務
- **連線與自動化** — 本地 API、MCP、可複用配方與監視資料夾

從預設的 **WisprStudio**（由 k2-fsa/OmniVoice 驅動）開始，或在模型管理器中從數十種其他引擎中挑選。參見[功能與引擎目錄](../../docs/feature-catalog.md)。

<p align="center"><a href="https://discord.gg/bzQavDfVV9"><img src="../../docs/assets/discord-community.svg" alt="Come say hello! Join us on Discord" height="64" /></a></p>

## Pro 和 Cloud

以上功能全部免費，在你自己的硬體上執行，不需要帳號。Pro 和 Cloud 皆為選用。

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="https://github.com/TheHalfMoon/wisprstudio"><img src="../assets/voicestudio-pro.svg" alt="" width="56" height="56" align="middle" /></a>&nbsp;&nbsp;<strong><a href="https://github.com/TheHalfMoon/wisprstudio">WisprStudio Pro</a></strong><br /><br />
      適合在多台機器上承接付費客戶專案。
      <ul>
        <li>用於客戶專案的商業授權，透過電子郵件寄給你</li>
        <li>一位使用者，最多同時使用 3 台裝置</li>
        <li>把工作傳送到你的其他 GPU，專案仍留在本機</li>
        <li>搶先取得新功能和修正</li>
      </ul>
      <sub>閉源版本，需要帳號，7 天內可全額退款。AGPL-3.0 應用程式依然免費，也可依其條款用於商業用途。</sub><br /><br />
      <strong><a href="https://github.com/TheHalfMoon/wisprstudio">查看 Pro 方案 →</a></strong>
    </td>
    <td width="50%" valign="top">
      <a href="https://github.com/TheHalfMoon/wisprstudio"><img src="../assets/voicestudio-cloud.svg" alt="" width="56" height="56" align="middle" /></a>&nbsp;&nbsp;<strong><a href="https://github.com/TheHalfMoon/wisprstudio">WisprStudio Cloud</a></strong><br /><br />
      託管的語音和配音 API，即將推出，不需要 GPU。
      <ul>
        <li>語音合成、聲音設計和經同意的聲音複製</li>
        <li>配音、轉錄和有聲書</li>
        <li>依日期或專案查看用量和點數</li>
        <li>長時間工作自動執行</li>
      </ul>
      <sub>尚未開放：加入搶先體驗即可獲得免費使用點數。桌面應用程式依然免費且在本機執行。</sub><br /><br />
      <strong><a href="https://github.com/TheHalfMoon/wisprstudio">加入 Cloud 搶先體驗 →</a></strong>
    </td>
  </tr>
</table>

<a id="platforms"></a>

## 支援平臺

選擇你的系統，再展開相應的安裝方式。

<a id="install-macos"></a>

<details>
<summary><img src="../../docs/assets/platforms/apple.svg" alt="" width="20" height="20" /> <strong>macOS</strong> · Homebrew · DMG · 安裝指令碼</summary>

<blockquote>

**穩定版 · Apple Silicon**<br />macOS 13.3+ · Apple Silicon：透過 Metal（MPS）執行本地引擎。

<a href="https://github.com/debpalash/homebrew-tap"><img src="https://img.shields.io/badge/Homebrew-27272a?style=flat-square&amp;logo=homebrew&amp;logoColor=ffffff" alt="Homebrew" height="20" /></a>

```sh
brew tap debpalash/tap
brew trust --cask debpalash/tap/voicestudio
brew install --cask debpalash/tap/voicestudio
```

<details>
<summary>DMG</summary>

下載適合你的 Mac 的 DMG，開啟後將 WisprStudio 拖入 Applications。

[下載](https://github.com/TheHalfMoon/wisprstudio/releases/latest) · [指南](../../docs/install/macos.md)

</details>

<details>
<summary>一條命令安裝</summary>

```sh
curl -fsSL https://github.com/TheHalfMoon/wisprstudio | sh
```

</details>

<details>
<summary>Intel Mac · 遠端後端 · 受限</summary>

Intel Mac 可執行應用介面；請連線另一臺電腦上的 WisprStudio 後端。

[指南](../../docs/install/macos.md)

</details>

> [!NOTE]
> 在 macOS 上看到“WisprStudio 已損壞，無法開啟”，是 Gatekeeper 攔截了應用，並不是下載檔案損壞。參見 [Gatekeeper 修復方法](../../docs/install/macos.md#gatekeeper-quarantine)。

</blockquote>

</details>

<a id="install-windows"></a>

<details>
<summary><img src="../../docs/assets/platforms/windows.svg" alt="" width="20" height="20" /> <strong>Windows</strong> · PowerShell · EXE</summary>

<blockquote>

**穩定版 · x64**<br />Windows 10/11 x64 · NVIDIA CUDA · AMD ROCm（需主動啟用）· CPU。

```powershell
irm https://github.com/TheHalfMoon/wisprstudio | iex
```

[下載 Windows 安裝程式](https://github.com/TheHalfMoon/wisprstudio/releases/latest) · [指南](../../docs/install/windows.md) · [AMD ROCm](../../docs/install/windows-rocm.md)

<details>
<summary>Windows on ARM · 實驗性</summary>

應用介面原生執行；x64 Python 後端透過模擬在 CPU 上執行。

[下載](https://github.com/TheHalfMoon/wisprstudio/releases/latest) · [指南](../../docs/install/windows.md)

</details>

</blockquote>

</details>

<a id="install-linux"></a>

<details open>
<summary><img src="../../docs/assets/platforms/linux.svg" alt="" width="20" height="20" /> <strong>Linux</strong> · AUR · Snap · DEB · AppImage · Nix</summary>

<blockquote>

**穩定版 · x64**<br />Linux x64 · NVIDIA CUDA · CPU · 支援的 GGUF 引擎可使用 Vulkan。

<details>
<summary>一條命令安裝</summary>

```sh
curl -fsSL https://github.com/TheHalfMoon/wisprstudio | sh
```

</details>

<details>
<summary>Arch / Manjaro / EndeavourOS · AUR</summary>

<a href="https://aur.archlinux.org/packages/voicestudio-bin"><img src="https://img.shields.io/badge/AUR-1793d1?style=flat-square&amp;logo=archlinux&amp;logoColor=ffffff" alt="AUR" height="20" /></a>

```sh
yay -S voicestudio-bin
```

也可以使用 `paru -S voicestudio-bin` 安裝。

[開發原始碼版](https://aur.archlinux.org/packages/voicestudio-git) · `yay -S voicestudio-git`

<details>
<summary>從 AUR 構建並使用 pacman 安裝</summary>

```sh
sudo pacman -S --needed base-devel git
git clone https://aur.archlinux.org/voicestudio-bin.git
cd voicestudio-bin
makepkg -s
sudo pacman -U ./voicestudio-bin-*.pkg.tar.zst
```

</details>

</details>

<details>
<summary>Ubuntu / Debian / Linux Mint · DEB</summary>

將 `.deb` 下載到當前目錄，再安裝：

[下載](https://github.com/TheHalfMoon/wisprstudio/releases/latest)

```sh
sudo apt install ./WisprStudio-*-linux-x64.deb
```

</details>

<details>
<summary>Snap · Ubuntu、Fedora、openSUSE 等</summary>

<a href="https://snapcraft.io/voicestudio"><img src="https://img.shields.io/badge/Snap%20Store-27272a?style=flat-square&amp;logo=snapcraft&amp;logoColor=ffffff" alt="Snap Store" height="20" /></a>

[安裝 snapd](https://snapcraft.io/docs/installing-snapd) 後執行：

```sh
sudo snap install voicestudio
```

如需啟用麥克風訪問：

```sh
sudo snap connect voicestudio:audio-record
```

</details>

<details>
<summary>各類 Linux 發行版 · AppImage</summary>

將 AppImage 下載到當前目錄，再啟動：

[下載](https://github.com/TheHalfMoon/wisprstudio/releases/latest)

```sh
chmod +x WisprStudio-*-linux-x64.AppImage
./WisprStudio-*-linux-x64.AppImage
```

</details>

<details>
<summary>Nix / NixOS · 原始碼環境</summary>

進入倉庫提供的 FHS 開發環境，再從原始碼啟動：

```sh
git clone https://github.com/TheHalfMoon/wisprstudio.git
cd WisprStudio
nix develop .#fhs
bun run dev
```

[指南](../../docs/install/nix.md)

</details>

[指南](../../docs/install/linux.md)

</blockquote>

</details>

<a id="install-docker"></a>

<details>
<summary><img src="../../docs/assets/platforms/docker.svg" alt="" width="20" height="20" /> <strong>Docker</strong> · GHCR · Docker Hub</summary>

<blockquote>

穩定版映象 · CPU · NVIDIA CUDA · AMD ROCm。

<a href="https://github.com/TheHalfMoon/wisprstudio/pkgs/container/voicestudio"><img src="https://img.shields.io/badge/GHCR-27272a?style=flat-square&amp;logo=github&amp;logoColor=ffffff" alt="GHCR" height="20" /></a>

**在本機使用 CPU 執行（Bash）**

```sh
export OMNIVOICE_API_KEY="$(openssl rand -hex 32)"
docker run -d --name omnivoice \
  -p 127.0.0.1:3900:3900 \
  -e OMNIVOICE_API_KEY \
  -e OMNIVOICE_DATA_DIR=/app/omnivoice_data \
  -v omnivoice-data:/app/omnivoice_data \
  ghcr.io/debpalash/voicestudio:stable
printf 'API key: %s\n' "$OMNIVOICE_API_KEY"
```

開啟 http://localhost:3900，並使用下方輸出的 API 金鑰。

[NVIDIA、AMD ROCm 和 Compose 使用說明](../../docs/install/docker.md)

[Docker Hub 映象](https://hub.docker.com/r/palashdeb/omnivoice-studio): `palashdeb/omnivoice-studio:stable`

</blockquote>

</details>

<a id="install-android"></a>

<details>
<summary><img src="../../docs/assets/platforms/android.svg" alt="" width="20" height="20" /> <strong>Android</strong> · APK · Obtainium · F-Droid 軟體倉庫</summary>

<blockquote>

Android 10+ · 預覽版 · 下載模型後可在裝置上離線執行。

[下載 APK](https://github.com/TheHalfMoon/wisprstudio/releases/latest) · [指南](../../docs/mobile.md#install)

<details>
<summary>F-Droid · WisprStudio 軟體倉庫</summary>

在相容 F-Droid 的客戶端中新增此倉庫，並按照指南核對指紋。

```text
https://debpalash.github.io/WisprStudio/fdroid/repo
```

[指南](../../store/fdroid/README.md)

</details>

<details>
<summary>Obtainium · GitHub 發行版</summary>

在 Obtainium 中新增此來源，或匯入提供的配置。

```text
https://github.com/TheHalfMoon/wisprstudio
```

[匯入配置](https://debpalash.github.io/WisprStudio/obtainium.json)

</details>

<details>
<summary>透過 USB 使用 adb 安裝</summary>

```sh
adb install -r WisprStudio-*-android.apk
```

</details>

</blockquote>

</details>

<a id="install-ios"></a>

<details>
<summary><img src="../../docs/assets/platforms/apple.svg" alt="" width="20" height="20" /> <strong>iPhone / iPad</strong> · IPA · 側載</summary>

<blockquote>

iOS / iPadOS 17+ · 預覽版 · 下載模型後可在裝置上離線執行。

下載 IPA，並按照指南完成簽名和側載。

[下載](https://github.com/TheHalfMoon/wisprstudio/releases/latest) · [指南](../../docs/mobile.md#install)

</blockquote>

</details>

桌面端和手機安裝包都在[最新發行版](https://github.com/TheHalfMoon/wisprstudio/releases/latest)中，Docker 映象則釋出在 GHCR。沒有 GPU？應用在 CPU 上也能完整使用，只是速度較慢。原生 GGUF 引擎還能透過 Vulkan 使用 AMD、Intel 和 NVIDIA GPU；在 Windows 和 Linux 上，OmniVoice GGUF 會自動選擇 GPU 和模型量化（[OmniVoice](../../docs/engines/omnivoice-gguf.md#vulkan-acceleration)、[CosyVoice](../../docs/engines/cosyvoice-gguf.md)）。各引擎在不同硬體上的速度：[效能說明](../../docs/performance.md)。


<a id="get-started"></a>

## 開始使用

按上方方式安裝後，開啟 **聲音克隆**，選擇一個聲音或新增清晰的參考錄音，輸入文字並生成。應用會在下載模型前徵求你的同意。

<details>
<summary><strong>更多安裝方式</strong>：指定版本、當前 main、解除安裝、從原始碼安裝、透過編碼智慧體安裝</summary>

```sh
curl -fsSL https://github.com/TheHalfMoon/wisprstudio | sh -s -- --version X.Y.Z   # 安裝指定版本
curl -fsSL https://github.com/TheHalfMoon/wisprstudio | sh -s -- --main            # 構建當前 main
curl -fsSL https://github.com/TheHalfMoon/wisprstudio | sh -s -- --uninstall       # 解除安裝應用，保留資料
```

如果無法訪問 `voicestudio.sh`，可直接從倉庫執行指令碼：
`curl -fsSL https://raw.githubusercontent.com/TheHalfMoon/wisprstudio/main/scripts/install.sh | sh`。
前置要求與指令碼行為：[安裝指令碼說明](../../docs/install/script.md)。

**從原始碼安裝**

```bash
git clone https://github.com/TheHalfMoon/wisprstudio.git
cd WisprStudio
bun run dev
```

`bun run dev` 會先安裝 JavaScript 依賴；使用受支援的本地後端時，還會在啟動 Electron 前安裝 Python 依賴。如果只需重建 Python 環境，可直接執行 `bun run setup:api`。

參見 [Electron 設定](../../electron/README.md)。

**透過編碼智慧體安裝**（Claude Code、Codex、Cursor 等），貼上：

```text
Install the WisprStudio app on this device and verify it works, following
https://github.com/TheHalfMoon/wisprstudio/blob/main/docs/install/agent.md
```

從 0.5.3 或更早版本（Tauri 應用）升級？請[單獨安裝新應用](../../docs/electron-migration.md)。

</details>

<a id="documentation"></a>

## 文件

[所有指南](../../docs/README.md)

| 需求 | 從這裡開始 |
|---|---|
| 安裝幫助 | [故障排查](../../docs/install/troubleshooting.md) · [模型下載](../../docs/downloading-models.md) |
| 指南 | [多說話人配音](../../docs/dubbing/multi-speaker-guide.md) · [富有表現力的語音](../../docs/expressive-speech.md) · [匯出配音](../../docs/dubbing/export.md) |
| 模型與音質 | [引擎指南](../../docs/engines/README.md) · [whisper.cpp ASR](../../docs/engines/whisper-cpp.md) · [效能基準](../../docs/benchmarks.md) |
| 整合 | [本地 API](../../docs/speech-platform.md) · [MCP](../../docs/mcp.md) · [示例](../../examples/README.md) |
| 手機應用 | [iOS 與 Android](../../docs/mobile.md) |
| 開發 | [參與貢獻](../../.github/CONTRIBUTING.md)（首次提交 PR 前請[簽署 CLA](../../.github/CONTRIBUTING.md#contribution-licensing)）· [更新日誌](../../CHANGELOG.md) |

智慧體技能：`npx skills add TheHalfMoon/wisprstudio`（音訊工作用 **voicestudio**，倉庫維護用 **voicestudio-maintainer**）。

<a id="sponsors"></a>

## 贊助者

WisprStudio 應用程式免費使用，不需要付費雲服務。贊助者讓它持續釋出新版本：贊助資金用於維護者時間、測試硬體、程式碼簽名和釋出基礎設施。


如有贊助意向，請聯絡 [TheHalfMoon/wisprstudio](https://github.com/TheHalfMoon/wisprstudio)。

<a href="https://github.com/sponsors/debpalash"><img src="https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-ea4aaa?logo=githubsponsors&logoColor=white" alt="透過 GitHub Sponsors 贊助" /></a>

<a id="other-projects"></a>

## 其他專案

探索 WisprStudio 開發者打造的更多開源工具。

- **[OpenGTM](https://github.com/debpalash/OpenGTM)** — 在自託管的市場拓展工作區中發現企業和聯絡人，並完善相關資料。 [原始碼](https://github.com/debpalash/OpenGTM).
- **[Opal](https://github.com/debpalash/Opal)** — 在一個原生開源播放器中觀看、串流和瀏覽媒體。 [原始碼](https://github.com/debpalash/Opal).

更多專案: [debpalash](https://github.com/debpalash?tab=repositories) · [velixio](https://github.com/velixio?tab=repositories)

<a id="team"></a>

## 團隊

<a id="core-team"></a>

### 核心團隊

<table>
<tr>
<td align="center" width="200"><a href="https://github.com/debpalash"><img src="https://github.com/debpalash.png?size=160" width="80" height="80" alt="Palash Debnath"></a><br><b>Palash Debnath</b><br><sub>創始人與核心團隊</sub><br><sub><a href="https://palash.dev">palash.dev</a> · <a href="https://github.com/debpalash">GitHub</a> · <a href="https://x.com/idebpalash">X</a></sub></td>
<td align="center" width="200"><a href="https://github.com/velixio"><img src="https://github.com/velixio.png?size=160" width="80" height="80" alt="Shimul Debnath"></a><br><b>Shimul Debnath</b><br><sub>核心團隊</sub><br><sub><a href="https://shimul.me">shimul.me</a> · <a href="https://github.com/velixio">GitHub</a> · <a href="https://x.com/shimuldn">X</a></sub></td>
</tr>
</table>

<a id="contributors"></a>

### 貢獻者

<a href="https://github.com/kevin9327"><img src="https://github.com/kevin9327.png?size=96" width="44" height="44" alt="@kevin9327" title="@kevin9327"></a> <a href="https://github.com/jaketame"><img src="https://github.com/jaketame.png?size=96" width="44" height="44" alt="@jaketame" title="@jaketame"></a> <a href="https://github.com/psiberfunk"><img src="https://github.com/psiberfunk.png?size=96" width="44" height="44" alt="@psiberfunk" title="@psiberfunk"></a> <a href="https://github.com/rudycelekli"><img src="https://github.com/rudycelekli.png?size=96" width="44" height="44" alt="@rudycelekli" title="@rudycelekli"></a> <a href="https://github.com/paoloantinori"><img src="https://github.com/paoloantinori.png?size=96" width="44" height="44" alt="@paoloantinori" title="@paoloantinori"></a> <a href="https://github.com/Chang-Jin-Lee"><img src="https://github.com/Chang-Jin-Lee.png?size=96" width="44" height="44" alt="@Chang-Jin-Lee" title="@Chang-Jin-Lee"></a> <a href="https://github.com/swadhinbiswas"><img src="https://github.com/swadhinbiswas.png?size=96" width="44" height="44" alt="@swadhinbiswas" title="@swadhinbiswas"></a> <a href="https://github.com/BichengWang"><img src="https://github.com/BichengWang.png?size=96" width="44" height="44" alt="@BichengWang" title="@BichengWang"></a> <a href="https://github.com/nirmalchatur"><img src="https://github.com/nirmalchatur.png?size=96" width="44" height="44" alt="@nirmalchatur" title="@nirmalchatur"></a> <a href="https://github.com/Shivendra-Coherent"><img src="https://github.com/Shivendra-Coherent.png?size=96" width="44" height="44" alt="@Shivendra-Coherent" title="@Shivendra-Coherent"></a> <a href="https://github.com/marreiradigital"><img src="https://github.com/marreiradigital.png?size=96" width="44" height="44" alt="@marreiradigital" title="@marreiradigital"></a> <a href="https://github.com/nvtoan0201-swe"><img src="https://github.com/nvtoan0201-swe.png?size=96" width="44" height="44" alt="@nvtoan0201-swe" title="@nvtoan0201-swe"></a>

感謝所有貢獻程式碼、報告、翻譯和想法的人。[檢視全部貢獻者](https://github.com/TheHalfMoon/wisprstudio/graphs/contributors) · [參與貢獻](../../.github/CONTRIBUTING.md)

<a id="license--responsible-use"></a>

## 許可證與負責任使用

[AGPL-3.0](../../LICENSE) 覆蓋本應用，包括在其條款下的商業用途。模型權重、聲音和生成內容各有其許可證，模型管理器會為每個模型列出（[清單](../../docs/licensing/model-inventory.md)）。只有在聲音所有者許可的情況下才能克隆其聲音。詳情：[LICENSE-NOTICE.md](../../LICENSE-NOTICE.md) · [AGPL-3.0 Source](https://github.com/TheHalfMoon/wisprstudio)。

<a id="community-tutorials"></a>

## 社群教程

<p align="center">
  <a href="https://www.youtube.com/watch?v=I-u-A-oisIU&amp;utm_source=github&amp;utm_medium=readme&amp;utm_campaign=community_tutorials"><img src="https://i.ytimg.com/vi/I-u-A-oisIU/hqdefault.jpg" alt="WisprStudio tutorial by Nafay 3D on YouTube" width="30%" /></a>
  <a href="https://www.youtube.com/watch?v=hsLRbXLBP4U&amp;utm_source=github&amp;utm_medium=readme&amp;utm_campaign=community_tutorials"><img src="https://i.ytimg.com/vi/hsLRbXLBP4U/hqdefault.jpg" alt="WisprStudio tutorial by Samuel Gregory on YouTube" width="30%" /></a>
  <a href="https://www.youtube.com/watch?v=2KemGhEI0Ck&amp;utm_source=github&amp;utm_medium=readme&amp;utm_campaign=community_tutorials"><img src="https://i.ytimg.com/vi/2KemGhEI0Ck/hqdefault.jpg" alt="WisprStudio tutorial by kilObit on YouTube" width="30%" /></a><br />
  <sub>Nafay 3D · Samuel Gregory · kilObit</sub>
</p>

<p align="center"><a href="https://discord.gg/bzQavDfVV9"><img src="../../docs/assets/discord-community.svg" alt="Come say hello! Join us on Discord" height="64" /></a></p>
