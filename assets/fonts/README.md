# 应用字体 / Bundled Fonts

把中文字体文件放到本目录，应用启动时会自动扫描注册（支持 .ttf / .otf / .ttc）。

## 当前首选：MiSans

放入以下任一文件即可（文件名不限，识别的是字体内部 family 名 `MiSans`）：

- `MiSans-Regular.ttf`
- 或整套 MiSans 字重

### 下载

MiSans 由小米开源、免费商用。官方下载：
https://hyperos.mi.com/font/download/

下载后把 `MiSans-Regular.ttf`（以及需要的字重，如 Medium/Semibold）复制到本目录即可。

## 回退

若本目录为空或字体加载失败，应用会回退到系统已安装的
`MiSans` → `Microsoft YaHei UI` → `Microsoft YaHei`（见 `app/ui/fonts.py`）。
