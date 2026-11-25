The files in `technologies/` and `categories.json` are the Wappalyzer-format
signatures from Enthec's WebAppAnalyzer, the maintained open fork of the
technology catalog.

Source: https://github.com/enthec/webappanalyzer
License: GNU General Public License v3.0. The license text is `LICENSE` in
this directory. The commit recorded in `SOURCE_COMMIT` is the snapshot that
was copied.

The matcher in `site_scanner/fingerprint.py` is Beigefield code. It reads
these files. It does not include the WebAppAnalyzer program.

Refreshing the snapshot: `python site-scanner/tools/refresh_webappanalyzer.py`
