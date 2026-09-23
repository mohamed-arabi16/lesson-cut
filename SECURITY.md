# Security

lesson-cut runs locally. Its one secret, an optional ElevenLabs API key, is read only from the
`ELEVENLABS_API_KEY` environment variable or from `~/.lesson-cut/env` (`$LESSON_CUT_HOME/env` when
that is set), never from the plugin folder or a project. With a key, each take's audio track is
uploaded to ElevenLabs for transcription; with the local backend, nothing leaves the machine.

## Reporting a vulnerability

Report it privately, through GitHub: this repository's **Security** tab, then **Report a
vulnerability**. Please do not open a public issue for it.

Never paste an API key into an issue, a pull request or a report. If a key has been exposed
anywhere, revoke it in your ElevenLabs account and make a new one.

Only the latest release is supported.
