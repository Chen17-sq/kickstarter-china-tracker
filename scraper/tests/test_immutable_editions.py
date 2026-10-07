"""Recovery must preserve already published editions, including their PDF."""
import datetime as dt

from scraper import email_notify, pdf, report
from scraper.atomic import write_versioned_text


def test_changed_rerun_versions_and_identical_rerun_is_idempotent(tmp_path):
    original = tmp_path / '2026-10-07.md'
    assert write_versioned_text(original, 'original') == original
    revision = write_versioned_text(original, 'recovered')
    assert revision != original
    assert original.read_text() == 'original'
    assert revision.read_text() == 'recovered'
    assert write_versioned_text(original, 'recovered') == revision
    assert len(list(tmp_path.glob('*.md'))) == 2


def test_archive_and_pdf_preserve_original_and_latest_tracks_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(email_notify, 'REPO_ROOT', tmp_path)
    editions = tmp_path / 'site/editions'
    monkeypatch.setattr(pdf, 'EDITIONS', editions)
    first = email_notify.write_archive('<html>sent original</html>')
    first_pdf = first.with_suffix('.pdf')
    first_pdf.write_bytes(b'original-pdf')
    revision = email_notify.write_archive('<html>recovered preview</html>')
    calls = []
    async def fake_render(url, target):
        calls.append(url)
        target.write_bytes(b'revision-pdf')
    monkeypatch.setattr(pdf, '_render_pdf', fake_render)
    assert pdf.render_today() == revision.with_suffix('.pdf')
    assert first.read_text() == '<html>sent original</html>'
    assert first_pdf.read_bytes() == b'original-pdf'
    assert (editions / 'latest.html').read_text() == revision.read_text()
    assert (editions / 'latest.pdf').read_bytes() == b'revision-pdf'
    assert revision.name in (editions / 'index.html').read_text()
    assert '修订预览' in (editions / 'index.html').read_text()
    assert pdf.render_today() == revision.with_suffix('.pdf')
    assert len(calls) == 1


def test_standalone_report_preserves_dated_report(tmp_path, monkeypatch):
    source = tmp_path / 'projects.json'
    source.write_text('{"projects":[]}')
    monkeypatch.setattr(report, 'PROJECTS', source)
    monkeypatch.setattr(report, 'REPORTS', tmp_path)
    monkeypatch.setattr(report, 'find_prev_snapshot', lambda: None)
    monkeypatch.setattr(report, 'make_report', lambda *_: 'recovered')
    dated = tmp_path / (dt.datetime.now(dt.UTC).strftime('%Y-%m-%d') + '.md')
    dated.write_text('original')
    revised = report.write_today()
    assert revised != dated
    assert dated.read_text() == 'original'
    assert revised.read_text() == (tmp_path / 'latest.md').read_text() == 'recovered'
