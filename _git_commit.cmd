@echo off
D:
cd \DramaClip
git add -A
git commit -m "feat: integrate StyleTTS 2 as default TTS engine

- Add styletts2_tts() in voice.py with auto-emotion + voice cloning
- Add _synthesize_styletts2() in narration pipeline
- Set styletts2 as default tts_engine (schema.py, pipeline.py, config.example.toml)
- Add StyleTTS 2 option in SettingsPage frontend
- Fallback route also defaults to styletts2

Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"
