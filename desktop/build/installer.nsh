; 卸载清理选项：删除模型与运行环境（2026-11-19 需求）。
; 数据目录真值由应用启动时写注册表（main/index.ts registerDataDirForUninstaller）
; ——NSIS 拿不到应用内存储重定向，只有那里知道真值；读不到回退打包态默认
; （%APPDATA%\DramaClip\data）。models/runtimes/cache 是占盘大头；成片、项目库、
; BGM 曲库、日志一律保留（重装即恢复工作现场，模型重新下载即可）。
; 静默卸载（/S）确定性保数据：2026-11-20 装测实锤 /S 也会弹窗、点「是」即删数 GB
; ——脚本化/企业部署无人应答，必须不弹、直接走保留分支（交互卸载照常询问）。
!include "LogicLib.nsh"
!macro customUnInstall
  ReadRegStr $R0 HKCU "Software\DramaClip" "DataDir"
  StrCmp $R0 "" 0 +2
    StrCpy $R0 "$APPDATA\DramaClip\data"
  ${If} ${Silent}
    DetailPrint "静默卸载：保留模型与运行环境（交互卸载可自选删除）"
    GoTo uninstall_done
  ${EndIf}
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
    "是否同时删除模型与本地运行环境？$\n$\n将删除：$R0 下的$\n  models（模型资产）、runtimes（本地智能运行环境）、cache（分析缓存）$\n可能占用数 GB，删除需要一点时间。$\n$\n选「否」保留：重装后无需重新下载。成片、项目库、BGM 曲库、日志一律不受影响。" \
    IDNO uninstall_done
  DetailPrint "正在删除模型与运行环境（大目录可能需要一分钟）…"
  RMDir /r "$R0\models"
  RMDir /r "$R0\runtimes"
  RMDir /r "$R0\cache"
uninstall_done:
!macroend
