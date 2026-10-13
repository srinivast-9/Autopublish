from __future__ import annotations
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app

MATE_PGN='[Event "Mate test"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0'

class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app._load_sprites()

    def test_all_twelve_neo_sprites_load(self):
        self.assertEqual(len(app.PIECES),12)
        self.assertEqual(set(app.PIECES),{c+p for c in 'wb' for p in 'KQRBNP'})

    def test_rejects_non_https_and_untrusted_audio_url(self):
        with self.assertRaises(Exception):
            app._safe_url('http://example.com/audio.mp3')
        with self.assertRaises(Exception):
            app._safe_url('https://127.0.0.1/internal')

    def test_accepts_runway_signed_cdn_url(self):
        self.assertIn('cloudfront.net',app._safe_url('https://audio.cloudfront.net/signed/file.mp3?token=redacted'))

    def test_puzzle_requires_legal_checkmate(self):
        _,states,moves,sans,mate=app._parse_game(MATE_PGN,True)
        self.assertTrue(mate)
        self.assertEqual(sans[-1],'Qxf7#')
        self.assertEqual(len(states),len(moves)+1)

    def test_rejects_non_mating_line_when_mate_required(self):
        pgn='[Event "Not mate"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *'
        with self.assertRaises(RuntimeError):
            app._parse_game(pgn,True)

    def test_offline_render_smoke_with_mocked_audio_download(self):
        # This verifies FFmpeg, sprites, frame renderer, MP4 QA and mate-line
        # enforcement without relying on outbound CDN access in the build.
        with tempfile.TemporaryDirectory(prefix='chessbits-smoke-') as td:
            data_dir=Path(td)
            old_jobs=app.JOBS_ROOT
            app.JOBS_ROOT=data_dir/'jobs'
            app.JOBS_ROOT.mkdir(parents=True)
            job_id='a'*32
            def fake_download(url,target,total_bytes):
                target.parent.mkdir(parents=True,exist_ok=True)
                cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','3','-f','wav',str(target)]
                subprocess.run(cmd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
                return target.stat().st_size
            req=app.RenderRequest(pgn=MATE_PGN,voiceover_urls=['https://audio.cloudfront.net/test.mp3'],video_type='puzzle_short',title='Mate test',require_checkmate=True)
            try:
                with patch('app._download_audio',side_effect=fake_download):
                    result=app._render_video(job_id,req)
                self.assertTrue(Path(result['file']).is_file())
                self.assertGreater(result['bytes'],1000)
                self.assertTrue(result['checkmate_confirmed'])
                self.assertEqual((result['width'],result['height']),(1080,1920))
                self.assertIn(result['audio_codec'],('aac','mp3'))
            finally:
                app.JOBS_ROOT=old_jobs

if __name__=='__main__':
    unittest.main(verbosity=2)
