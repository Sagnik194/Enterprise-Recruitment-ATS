import io
import pytest
from pypdf import PdfWriter
from app.hardening import new_browser_session, validate_browser_session, password_fingerprint, validate_jwt_password_version
from app.login_guard import LoginGuard
from app.pdf_guard import validate_resume_pdf, InvalidResume

SECRET = 'a' * 48

def make_pdf():
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(stream)
    return stream.getvalue()

def test_session_valid():
    session = {'csrf': 'old'}
    new_browser_session(session, 7, 'hash-1', SECRET, now=100)
    assert session['user_id'] == 7
    assert session['csrf'] != 'old'
    assert validate_browser_session(session, 'hash-1', SECRET, now=200)

def test_session_expired():
    session = {}
    new_browser_session(session, 7, 'hash-1', SECRET, now=100)
    assert not validate_browser_session(session, 'hash-1', SECRET, now=3700)

def test_password_change_revokes_session():
    session = {}
    new_browser_session(session, 7, 'hash-1', SECRET, now=100)
    assert not validate_browser_session(session, 'hash-2', SECRET, now=200)

def test_password_change_revokes_jwt():
    claims = {'pwdv': password_fingerprint('hash-1', SECRET)}
    assert validate_jwt_password_version(claims, 'hash-1', SECRET)
    assert not validate_jwt_password_version(claims, 'hash-2', SECRET)
    assert not validate_jwt_password_version({}, 'hash-1', SECRET)

def test_login_guard_counts_only_failures():
    guard = LoginGuard(2, 60)
    guard.record_failure('ip', now=0)
    assert guard.allowed('ip', now=1)
    guard.record_failure('ip', now=2)
    assert not guard.allowed('ip', now=3)
    assert guard.allowed('ip', now=61)

def test_login_guard_success_clears_failures():
    guard = LoginGuard(1, 60)
    guard.record_failure('ip', now=0)
    guard.record_success('ip')
    assert guard.allowed('ip', now=1)

def test_pdf_accepts_real_document():
    assert validate_resume_pdf(make_pdf(), 'resume.pdf')

def test_pdf_rejects_fake_header():
    with pytest.raises(InvalidResume):
        validate_resume_pdf(b'%PDF-1.4\n%%EOF', 'resume.pdf')

def test_pdf_rejects_non_pdf_extension():
    with pytest.raises(InvalidResume):
        validate_resume_pdf(make_pdf(), 'resume.exe')

def test_pdf_rejects_oversized():
    with pytest.raises(InvalidResume):
        validate_resume_pdf(make_pdf(), 'resume.pdf', max_bytes=10)
