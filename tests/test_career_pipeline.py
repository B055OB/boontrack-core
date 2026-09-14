import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

from app.services.storage.r2 import R2Client, r2_client
from app.tenants.career.parser import parse_resume_buffer
from app.tenants.career.service import career_service
from app.main import app

client = TestClient(app)


def _create_sample_pdf_bytes(text: str = "John Doe Software Engineer with Python and AWS experience.") -> bytes:
    """Helper to generate a minimal in-memory PDF without touching disk."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [Paragraph(text, styles["Normal"])]
    doc.build(story)
    return buf.getvalue()


# ============================================================================
# 1. R2 CLIENT TESTS
# ============================================================================

def test_r2_client_upload_bytes():
    """Verify R2Client uploads bytes and returns canonical assets.boontrack.com URL."""
    custom_client = R2Client(
        account_id="test_acc",
        access_key_id="test_key",
        secret_access_key="test_secret",
        bucket_name="test_bucket",
        public_domain="assets.boontrack.com"
    )

    mock_s3 = MagicMock()
    custom_client._s3_client = mock_s3

    pdf_bytes = b"%PDF-1.4 test document content"
    dest_key = "resumes/user123/raw/12345678_cv.pdf"
    
    url = custom_client.upload_bytes(pdf_bytes, dest_key, content_type="application/pdf")

    assert url == f"https://assets.boontrack.com/{dest_key}"
    mock_s3.put_object.assert_called_once_with(
        Bucket="test_bucket",
        Key=dest_key,
        Body=pdf_bytes,
        ContentType="application/pdf"
    )


def test_r2_client_upload_bytesio():
    """Verify R2Client handles io.BytesIO buffer input correctly."""
    custom_client = R2Client(
        account_id="test_acc",
        access_key_id="test_key",
        secret_access_key="test_secret",
        bucket_name="test_bucket",
        public_domain="assets.boontrack.com"
    )

    mock_s3 = MagicMock()
    custom_client._s3_client = mock_s3

    raw_data = b"In-memory stream binary data"
    buffer = io.BytesIO(raw_data)
    dest_key = "resumes/candidate/raw/test.pdf"

    url = custom_client.upload_bytes(buffer, dest_key, content_type="application/pdf")

    assert url == f"https://assets.boontrack.com/{dest_key}"
    mock_s3.put_object.assert_called_once_with(
        Bucket="test_bucket",
        Key=dest_key,
        Body=raw_data,
        ContentType="application/pdf"
    )


@pytest.mark.asyncio
async def test_r2_client_upload_async():
    """Verify async wrapper delegates to thread pool and returns canonical URL."""
    custom_client = R2Client(
        public_domain="assets.boontrack.com"
    )
    with patch.object(custom_client, "upload_bytes", return_value="https://assets.boontrack.com/test_key.pdf") as mock_up:
        url = await custom_client.upload_bytes_async(b"abc", "test_key.pdf")
        assert url == "https://assets.boontrack.com/test_key.pdf"
        mock_up.assert_called_once()


# ============================================================================
# 2. IN-MEMORY PARSER TESTS
# ============================================================================

def test_parse_resume_buffer_pdf():
    """Verify in-memory resume parser extracts text from PDF stream with zero disk writes."""
    expected_text = "Jane Doe Senior Data Engineer Cloudflare Supabase"
    pdf_bytes = _create_sample_pdf_bytes(expected_text)
    
    buf = io.BytesIO(pdf_bytes)
    result = parse_resume_buffer(buf, filename="Jane_Doe_CV.pdf")

    assert isinstance(result, str)
    assert "Jane Doe" in result
    assert "Senior Data Engineer" in result


def test_parse_resume_buffer_empty():
    """Verify parser handles empty or corrupt stream gracefully."""
    empty_buf = io.BytesIO(b"")
    result = parse_resume_buffer(empty_buf, filename="empty.pdf")
    assert isinstance(result, str)
    assert result == ""


# ============================================================================
# 3. CAREER SERVICE INGESTION & GENERATION PIPELINE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_career_service_ingest_raw_cv():
    """Verify career_service.ingest_raw_cv flows in-memory, saves to R2, and logs metadata only."""
    user_id = "test_user_888"
    pdf_bytes = _create_sample_pdf_bytes("Alice Engineer Python FastAPI AWS Docker")
    
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute.return_value = MagicMock(data=[{"id": "res_db_123"}])
    mock_table.insert.return_value = mock_insert
    mock_supabase.table.return_value = mock_table

    with patch("app.tenants.career.service.r2_client.upload_bytes_async") as mock_r2_upload, \
         patch("app.tenants.career.service.get_supabase", return_value=mock_supabase), \
         patch("app.tenants.career.service.cv_review_engine.evaluate_cv") as mock_eval:
        
        mock_r2_upload.side_effect = lambda buf, key, content_type: f"https://assets.boontrack.com/{key}"
        mock_eval.return_value = {
            "score": 85,
            "strengths": ["FastAPI", "Python"],
            "recommendations": ["Add ATS summary"]
        }

        result = await career_service.ingest_raw_cv(
            user_id=user_id,
            file_buffer=io.BytesIO(pdf_bytes),
            filename="Alice_CV.pdf"
        )

        assert result["status"] == "success"
        assert result["raw_file_url"].startswith(f"https://assets.boontrack.com/resumes/{user_id}/raw/")
        assert "Alice_CV.pdf" in result["raw_file_url"]
        assert "Alice Engineer" in result["extracted_text"]

        # Ensure Supabase was called with metadata ONLY, never binary or base64
        mock_table.insert.assert_called_once()
        insert_args = mock_table.insert.call_args[0][0]
        assert insert_args["user_id"] == user_id
        assert insert_args["raw_file_url"] == result["raw_file_url"]
        assert "Alice_CV.pdf" in insert_args["filename"]
        # Confirm no binary or base64 data passed
        assert not isinstance(insert_args["raw_file_url"], (bytes, io.BytesIO))
        assert "data:application" not in insert_args["raw_file_url"]


@pytest.mark.asyncio
async def test_career_service_generate_and_upload_ats():
    """Verify career_service.generate_and_upload_ats builds in-memory PDF, uploads to R2, updates Supabase."""
    user_id = "test_user_999"
    resume_id = "res_db_123"

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_update = MagicMock()
    mock_update.eq.return_value.execute.return_value = MagicMock(data=[{"id": resume_id}])
    mock_table.update.return_value = mock_update
    mock_supabase.table.return_value = mock_table

    with patch("app.tenants.career.service.r2_client.upload_bytes_async") as mock_r2_upload, \
         patch("app.tenants.career.service.get_supabase", return_value=mock_supabase):
        
        mock_r2_upload.side_effect = lambda buf, key, content_type: f"https://assets.boontrack.com/{key}"

        result = await career_service.generate_and_upload_ats(
            user_id=user_id,
            parsed_content={"name": "Bob ATS", "contact": "bob@example.com"},
            analysis_result={"strengths": ["ReportLab", "Python"]},
            resume_id=resume_id,
        )

        assert result["status"] == "success"
        assert result["generated_file_url"].startswith(f"https://assets.boontrack.com/resumes/{user_id}/generated/ats_{user_id}_")
        assert result["generated_file_url"].endswith(".pdf")

        # Verify R2 upload arguments
        mock_r2_upload.assert_called_once()
        call_args = mock_r2_upload.call_args
        uploaded_buffer = call_args[0][0]
        assert isinstance(uploaded_buffer, io.BytesIO)
        # Content must be valid PDF stream
        uploaded_buffer.seek(0)
        assert uploaded_buffer.read(4) == b"%PDF"


# ============================================================================
# 4. FASTAPI ENDPOINT INTEGRATION TESTS
# ============================================================================

def test_fastapi_upload_cv_endpoint():
    """Test POST /api/v1/career/upload-cv endpoint via FastAPI client."""
    pdf_bytes = _create_sample_pdf_bytes("Michael Scott Regional Manager")

    with patch("app.tenants.career.service.career_service.ingest_raw_cv") as mock_ingest:
        mock_ingest.return_value = {
            "status": "success",
            "resume_id": "res_test_101",
            "user_id": "user_101",
            "filename": "michael_cv.pdf",
            "raw_file_url": "https://assets.boontrack.com/resumes/user_101/raw/1710000000_michael_cv.pdf",
            "extracted_text": "Michael Scott Regional Manager",
            "analysis_result": {"score": 90}
        }

        response = client.post(
            "/api/v1/career/upload-cv",
            data={"user_id": "user_101"},
            files={"file": ("michael_cv.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["raw_file_url"] == "https://assets.boontrack.com/resumes/user_101/raw/1710000000_michael_cv.pdf"
        assert data["user_id"] == "user_101"


def test_fastapi_generate_ats_endpoint():
    """Test POST /api/v1/career/generate-ats endpoint via FastAPI client."""
    with patch("app.tenants.career.service.career_service.generate_and_upload_ats") as mock_gen:
        mock_gen.return_value = {
            "status": "success",
            "user_id": "user_202",
            "destination_key": "resumes/user_202/generated/ats_user_202_1710000000.pdf",
            "generated_file_url": "https://assets.boontrack.com/resumes/user_202/generated/ats_user_202_1710000000.pdf",
        }

        response = client.post(
            "/api/v1/career/generate-ats",
            json={
                "user_id": "user_202",
                "resume_id": "res_test_101",
                "parsed_content": {"name": "Dwight Schrute"},
                "analysis_result": {"strengths": ["Sales", "Paper Distribution"]}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["generated_file_url"] == "https://assets.boontrack.com/resumes/user_202/generated/ats_user_202_1710000000.pdf"
        assert data["user_id"] == "user_202"


# ============================================================================
# 5. AIOHTTP ROUTE INTEGRATION TESTS
# ============================================================================

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from app.tenants.career.router import register_career_routes
import base64

class TestCareerAioHTTPRoutes(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_career_routes(app)
        return app

    @unittest_run_loop
    @patch("app.tenants.career.service.career_service.ingest_raw_cv")
    async def test_aiohttp_upload_cv_json(self, mock_ingest):
        mock_ingest.return_value = {
            "status": "success",
            "resume_id": "res_aio_1",
            "user_id": "user_aio_1",
            "raw_file_url": "https://assets.boontrack.com/resumes/user_aio_1/raw/1710000000_cv.pdf",
        }

        b64_str = base64.b64encode(b"%PDF-1.4 dummy pdf").decode("utf-8")
        resp = await self.client.post(
            "/api/v1/career/upload-cv",
            json={
                "user_id": "user_aio_1",
                "filename": "cv.pdf",
                "file_base64": b64_str
            }
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("assets.boontrack.com", data["raw_file_url"])

    @unittest_run_loop
    @patch("app.tenants.career.service.career_service.generate_and_upload_ats")
    async def test_aiohttp_generate_ats(self, mock_gen):
        mock_gen.return_value = {
            "status": "success",
            "user_id": "user_aio_2",
            "generated_file_url": "https://assets.boontrack.com/resumes/user_aio_2/generated/ats_user_aio_2_1710000000.pdf",
        }

        resp = await self.client.post(
            "/api/v1/career/generate-ats",
            json={
                "user_id": "user_aio_2",
                "parsed_content": {"name": "Test Candidate"}
            }
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("assets.boontrack.com", data["generated_file_url"])

