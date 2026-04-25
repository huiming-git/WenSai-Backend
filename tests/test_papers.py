import io


class TestCreatePaper:
    def test_create_paper(self, client, auth_headers):
        resp = client.post("/api/papers", json={
            "title": "My Research Paper",
            "abstract": "A brief abstract.",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "My Research Paper"
        assert data["status"] == "pending"

    def test_create_paper_no_auth(self, client):
        resp = client.post("/api/papers", json={"title": "Paper"})
        assert resp.status_code == 401


class TestListPapers:
    def test_list_papers(self, client, auth_headers, sample_paper):
        resp = client.get("/api/papers", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_list_papers_pagination(self, client, auth_headers):
        for i in range(3):
            client.post("/api/papers", json={"title": f"Paper {i}"}, headers=auth_headers)
        resp = client.get("/api/papers?page=1&page_size=2", headers=auth_headers)
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2


class TestGetPaper:
    def test_get_paper(self, client, auth_headers, sample_paper):
        resp = client.get(f"/api/papers/{sample_paper['id']}", headers=auth_headers)
        assert resp.status_code == 200

    def test_get_paper_not_found(self, client, auth_headers):
        resp = client.get("/api/papers/9999", headers=auth_headers)
        assert resp.status_code == 404


class TestUpdatePaper:
    def test_update_paper(self, client, auth_headers, sample_paper):
        resp = client.put(f"/api/papers/{sample_paper['id']}", json={"title": "Updated"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    def test_update_paper_not_owner(self, client, second_user_headers, sample_paper):
        resp = client.put(f"/api/papers/{sample_paper['id']}", json={"title": "Hacked"}, headers=second_user_headers)
        assert resp.status_code == 403


class TestDeletePaper:
    def test_delete_paper(self, client, auth_headers, sample_paper):
        resp = client.delete(f"/api/papers/{sample_paper['id']}", headers=auth_headers)
        assert resp.status_code == 204

    def test_delete_paper_not_owner(self, client, second_user_headers, sample_paper):
        resp = client.delete(f"/api/papers/{sample_paper['id']}", headers=second_user_headers)
        assert resp.status_code == 403


class TestUploadFile:
    def test_upload_pdf(self, client, auth_headers, sample_paper):
        pdf_content = b"%PDF-1.4 fake pdf content"
        resp = client.post(
            f"/api/papers/{sample_paper['id']}/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["file_path"] is not None

    def test_upload_docx(self, client, auth_headers, sample_paper):
        resp = client.post(
            f"/api/papers/{sample_paper['id']}/upload",
            files={"file": ("paper.docx", io.BytesIO(b"fake docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["file_path"].endswith(".docx")

    def test_upload_download_roundtrip(self, client, auth_headers, sample_paper):
        pptx_content = b"fake pptx payload"
        upload_resp = client.post(
            f"/api/papers/{sample_paper['id']}/upload",
            files={"file": ("slides.pptx", io.BytesIO(pptx_content), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
            headers=auth_headers,
        )
        assert upload_resp.status_code == 200
        assert upload_resp.json()["file_path"].endswith(".pptx")

        download_resp = client.get(f"/api/papers/{sample_paper['id']}/file", headers=auth_headers)
        assert download_resp.status_code == 200
        assert download_resp.content == pptx_content

    def test_upload_rejects_large_file(self, client, auth_headers, sample_paper, monkeypatch):
        monkeypatch.setattr("app.routers.papers.MAX_UPLOAD_SIZE_MB", 1)
        too_large = io.BytesIO(b"a" * (2 * 1024 * 1024))
        resp = client.post(
            f"/api/papers/{sample_paper['id']}/upload",
            files={"file": ("large.pdf", too_large, "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 413

    def test_upload_rejects_unsupported_extension(self, client, auth_headers, sample_paper):
        resp = client.post(
            f"/api/papers/{sample_paper['id']}/upload",
            files={"file": ("script.exe", io.BytesIO(b"bad"), "application/octet-stream")},
            headers=auth_headers,
        )
        assert resp.status_code == 400
