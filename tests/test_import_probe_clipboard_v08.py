"""Synthetic clipboard-style modal tests, NOT evidence about pokesleep-tool itself."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('probe_v08',R/'probe/run_import_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

HTML='''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Clipboard mock</title>
<style>
#box{position:absolute;top:319px;left:16px}
#box-menu{position:absolute;top:314px;right:8px}
#menu{position:absolute;right:5px;top:345px}
#menu:not(.show),[role=dialog]:not(.show){display:none}
[role=dialog]{position:absolute;left:300px;top:100px;z-index:5;background:white;padding:20px}
</style>
<textarea id="unrelated" style="position:absolute;left:60px;top:10px">Do not write here</textarea>
<button id="box" role="tab">ボックス</button>
<button id="box-menu" aria-label="actions" type="button">⋮</button>
<ul id="menu"><li role="menuitem" id="imp">インポート</li><li role="menuitem" id="exp">エクスポート</li></ul>
<div id="import-dialog" role="dialog"><h2>インポート</h2><textarea placeholder="ボックス情報" id="input"></textarea><button id="submit-import">インポート</button><button id="cancel">閉じる</button></div>
<div id="export-dialog" role="dialog"><h2>エクスポート</h2><textarea id="output" readonly></textarea><button id="close-exp">閉じる</button></div>
<script>
let content='';const menu=document.querySelector('#menu');
document.querySelector('#box-menu').onclick=()=>menu.classList.add('show');
document.querySelector('#imp').onclick=()=>{menu.classList.remove('show');document.querySelector('#import-dialog').classList.add('show')};
document.querySelector('#submit-import').onclick=()=>{content=document.querySelector('#input').value;document.querySelector('#import-dialog').classList.remove('show')};
document.querySelector('#exp').onclick=()=>{menu.classList.remove('show');document.querySelector('#export-dialog').classList.add('show');document.querySelector('#output').value=content};
</script></html>'''

class ClipboardUiTest(unittest.TestCase):
    def test_import_paste_and_export_textarea_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            rc=probe.browser_probe('about:blank',td,chromium_path='/usr/bin/chromium',mock_html=HTML)
            r=json.loads((Path(td)/'PROBE_RESULT.json').read_text())
            self.assertEqual(rc,0,r)
            self.assertEqual(r['status'],'MOCK_ROUNDTRIP_MATCH')
            self.assertFalse(r['upstreamImporterExecuted'])
            self.assertFalse(r['deployedAppChecked'])
            self.assertFalse(r['productionCsvAllowed'])
            self.assertIn('IMPORT_CSV_PASTED_AND_CONFIRMED',r['steps'])
            self.assertIn('EXPORT_CAPTURED_FROM_DIALOG_TEXTAREA',r['steps'])
            self.assertTrue((Path(td)/'roundtrip_export.csv').exists())

    def test_ui_changes_cell_and_must_hold(self):
        changed=HTML.replace("document.querySelector('#output').value=content", "document.querySelector('#output').value=content.replace('カメックス','フシギダネ')")
        with tempfile.TemporaryDirectory() as td:
            rc=probe.browser_probe('about:blank',td,chromium_path='/usr/bin/chromium',mock_html=changed)
            r=json.loads((Path(td)/'PROBE_RESULT.json').read_text())
            self.assertEqual(rc,2,r)
            self.assertEqual(r['status'],'HOLD')
            self.assertEqual(r['reason'],'CSV_ROUNDTRIP_NOT_EXACT')
            self.assertFalse(r['productionCsvAllowed'])
            self.assertFalse(r['importRoundTripExact'])

    def test_import_validation_error_is_explicit_and_never_passes(self):
        html=HTML.replace("content=document.querySelector('#input').value;document.querySelector('#import-dialog').classList.remove('show')",
           "document.querySelector('#import-dialog').insertAdjacentHTML('beforeend','<p role=alert>2件のデータを正しく読み取れませんでした。2行目のLv10の値が不正です</p>')")
        with tempfile.TemporaryDirectory() as td:
            rc=probe.browser_probe('about:blank',td,chromium_path='/usr/bin/chromium',mock_html=html)
            r=json.loads((Path(td)/'PROBE_RESULT.json').read_text())
            self.assertEqual(rc,2,r)
            self.assertEqual(r['reason'],'IMPORTER_VALIDATION_REJECTED')
            self.assertFalse(r['upstreamImporterExecuted'])
            self.assertIn('Lv10',r['importValidation']['summary'])
            self.assertTrue(r['importValidation']['validationMessages'])

    def test_no_import_dialog_does_not_fill_unrelated_textarea(self):
        without=HTML.replace('role="dialog"','role="region"')
        with tempfile.TemporaryDirectory() as td:
            rc=probe.browser_probe('about:blank',td,chromium_path='/usr/bin/chromium',mock_html=without)
            r=json.loads((Path(td)/'PROBE_RESULT.json').read_text())
            self.assertEqual(rc,2,r)
            self.assertEqual(r['status'],'HOLD')
            self.assertEqual(r['reason'],'IMPORT_INPUT_NOT_DISCOVERED')
            self.assertFalse(r['productionCsvAllowed'])
            self.assertNotIn('IMPORT_CSV_PASTED_AND_CONFIRMED',r['steps'])

    def test_no_export_dialog_does_not_forge_success(self):
        without=HTML.replace('id="export-dialog" role="dialog"','id="export-dialog" role="region"')
        with tempfile.TemporaryDirectory() as td:
            rc=probe.browser_probe('about:blank',td,chromium_path='/usr/bin/chromium',mock_html=without)
            r=json.loads((Path(td)/'PROBE_RESULT.json').read_text())
            self.assertEqual(rc,2,r)
            self.assertEqual(r['status'],'HOLD')
            self.assertEqual(r['reason'],'EXPORT_DIALOG_NOT_FOUND')
            self.assertFalse(r['productionCsvAllowed'])

if __name__=='__main__': unittest.main()
