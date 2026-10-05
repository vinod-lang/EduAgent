"""Central local-only PDF font resolution. No downloads or text substitution."""
from pathlib import Path
import os
import sys

class FontResolutionError(ValueError):
    pass


def packaged_fonts():
    # No font is currently bundled. Future additions require redistribution review
    # and the font's license in this exact assets directory before they are used.
    root=Path(__file__).resolve().parent/'assets'/'fonts'
    return (root/'DejaVuSans.ttf',) if (root/'LICENSE-DejaVu.txt').is_file() else ()


def system_fonts(platform=None):
    platform=sys.platform if platform is None else platform
    if platform=='darwin':
        return (Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),Path('/Library/Fonts/Arial Unicode.ttf'),Path('/System/Library/Fonts/Supplemental/Arial.ttf'))
    if platform.startswith('linux'):
        return (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'))
    if platform=='win32':
        root=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
        return (root/'arial.ttf',root/'segoeui.ttf')
    return ()


def covers_text(path,text):
    from fontTools.ttLib import TTFont
    try:
        with TTFont(path,lazy=True) as font:
            glyphs=font.getBestCmap() or {}
            return all(c.isspace() or ord(c) in glyphs for c in text)
    except Exception:
        # Font parser errors are expected for incompatible/corrupt local files.
        return False


def resolve_pdf_font(text,*,purpose=None,platform=None):
    if not isinstance(text,str):raise FontResolutionError('PDF font input must be text.')
    legacy={'document':'EDUAGENT_DOCUMENT_FONT','assessment':'EDUAGENT_ASSESSMENT_FONT'}
    key=legacy.get(purpose)
    override=os.environ.get(key) if key and key in os.environ else os.environ.get('EDUAGENT_PDF_FONT')
    explicit=override is not None
    if explicit:
        if not override.strip():raise FontResolutionError('PDF font override is blank. Set EDUAGENT_PDF_FONT to a local Unicode TTF font.')
        candidates=(Path(override).expanduser(),)
    else:candidates=packaged_fonts()+system_fonts(platform)
    for path in candidates:
        if path.is_file() and covers_text(path,text):return str(path)
    raise FontResolutionError('No local font covers the PDF text. Set EDUAGENT_PDF_FONT (or the workflow font override) to a suitable local Unicode TTF font. No text was dropped; no font was downloaded.')
