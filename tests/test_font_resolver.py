from pathlib import Path
from unittest.mock import Mock
import pytest
import font_resolver as fonts

@pytest.fixture(autouse=True)
def clear_font_env(monkeypatch):
    for key in ('EDUAGENT_PDF_FONT','EDUAGENT_DOCUMENT_FONT','EDUAGENT_ASSESSMENT_FONT'):
        monkeypatch.delenv(key,raising=False)


def dummy(tmp_path,name):
    p=tmp_path/name;p.write_bytes(b'synthetic font test boundary');return p


def test_shared_environment_override(tmp_path,monkeypatch):
    path=dummy(tmp_path,'font.ttf');monkeypatch.setenv('EDUAGENT_PDF_FONT',str(path))
    monkeypatch.setattr(fonts,'covers_text',lambda p,t:True)
    assert fonts.resolve_pdf_font('Synthetic',purpose='document')==str(path)
    assert fonts.resolve_pdf_font('Synthetic',purpose='assessment')==str(path)

@pytest.mark.parametrize('purpose,key',[('document','EDUAGENT_DOCUMENT_FONT'),('assessment','EDUAGENT_ASSESSMENT_FONT')])
def test_legacy_override_precedence(tmp_path,monkeypatch,purpose,key):
    one=dummy(tmp_path,'one.ttf');two=dummy(tmp_path,'two.ttf')
    monkeypatch.setenv('EDUAGENT_PDF_FONT',str(one));monkeypatch.setenv(key,str(two))
    monkeypatch.setattr(fonts,'covers_text',lambda p,t:True)
    assert fonts.resolve_pdf_font('Synthetic',purpose=purpose)==str(two)

@pytest.mark.parametrize('value',['','/nonexistent/private-font.ttf'])
def test_invalid_override_does_not_fall_back(monkeypatch,value):
    monkeypatch.setenv('EDUAGENT_PDF_FONT',value)
    with pytest.raises(fonts.FontResolutionError) as error:fonts.resolve_pdf_font('Synthetic')
    assert '/nonexistent' not in str(error.value)


def test_missing_glyphs_fail_safe(tmp_path,monkeypatch):
    p=dummy(tmp_path,'font.ttf');monkeypatch.setenv('EDUAGENT_PDF_FONT',str(p))
    monkeypatch.setattr(fonts,'covers_text',lambda p,t:False)
    with pytest.raises(fonts.FontResolutionError,match='No text was dropped'):fonts.resolve_pdf_font('講義')

@pytest.mark.parametrize('platform,expected',[('darwin','Arial Unicode.ttf'),('linux','DejaVuSans.ttf'),('win32','arial.ttf')])
def test_os_locations(platform,expected):
    assert fonts.system_fonts(platform)[0].name==expected

@pytest.mark.parametrize('platform',['darwin','linux'])
def test_os_resolution_mocked_no_real_fonts(tmp_path,monkeypatch,platform):
    p=dummy(tmp_path,platform+'.ttf')
    monkeypatch.setattr(fonts,'packaged_fonts',lambda:())
    chosen=Mock(return_value=(p,));monkeypatch.setattr(fonts,'system_fonts',chosen)
    monkeypatch.setattr(fonts,'covers_text',lambda p,t:True)
    assert fonts.resolve_pdf_font('Synthetic',platform=platform)==str(p)
    chosen.assert_called_once_with(platform)


def test_packaged_precedes_os_without_override(tmp_path,monkeypatch):
    packaged=dummy(tmp_path,'packaged.ttf');system=dummy(tmp_path,'system.ttf')
    monkeypatch.setattr(fonts,'packaged_fonts',lambda:(packaged,))
    monkeypatch.setattr(fonts,'system_fonts',lambda p:(system,))
    monkeypatch.setattr(fonts,'covers_text',lambda p,t:True)
    assert fonts.resolve_pdf_font('Synthetic')==str(packaged)


def test_no_packaged_font_without_license(tmp_path,monkeypatch):
    root=tmp_path/'assets'/'fonts';root.mkdir(parents=True);(root/'DejaVuSans.ttf').write_bytes(b'synthetic')
    monkeypatch.setattr(fonts,'__file__',str(tmp_path/'font_resolver.py'))
    assert fonts.packaged_fonts()==()
    (root/'LICENSE-DejaVu.txt').write_text('Synthetic license-presence fixture; no actual font bundled')
    assert fonts.packaged_fonts()==(root/'DejaVuSans.ttf',)


def test_corrupt_font_parser_controlled(tmp_path):
    assert not fonts.covers_text(dummy(tmp_path,'invalid.ttf'),'Synthetic')


def test_no_local_fonts_actionable(monkeypatch):
    monkeypatch.setattr(fonts,'packaged_fonts',lambda:())
    monkeypatch.setattr(fonts,'system_fonts',lambda p:())
    with pytest.raises(fonts.FontResolutionError,match='EDUAGENT_PDF_FONT'):fonts.resolve_pdf_font('Synthetic')
