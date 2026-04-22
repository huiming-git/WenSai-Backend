from unittest.mock import patch


class TestAiReview:
    @patch("app.routers.reviews._run_ai_review")
    def test_ai_review_returns_pending(self, mock_bg, client, auth_headers, sample_paper):
        """Endpoint should return a pending review immediately."""
        resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "ai"
        assert data["status"] == "pending"
        assert data["reviewer_id"] is None
        mock_bg.assert_called_once()

    @patch("app.routers.reviews._run_ai_review")
    def test_ai_review_duplicate(self, mock_bg, client, auth_headers, sample_paper):
        client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        assert resp.status_code == 400

    @patch("app.routers.reviews._run_ai_review")
    def test_ai_review_updates_paper_status(self, mock_bg, client, auth_headers, sample_paper):
        client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        resp = client.get(f"/api/papers/{sample_paper['id']}", headers=auth_headers)
        assert resp.json()["status"] == "under_review"

    def test_ai_review_paper_not_found(self, client, auth_headers):
        resp = client.post("/api/papers/9999/ai-review", headers=auth_headers)
        assert resp.status_code == 404


class TestManualReview:
    def test_create_manual_review(self, client, second_user_headers, sample_paper):
        resp = client.post(f"/api/papers/{sample_paper['id']}/reviews", json={
            "score": 8,
            "content": "Great paper.",
            "recommendation": "accept",
        }, headers=second_user_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "manual"
        assert data["status"] == "completed"
        assert data["reviewer_id"] is not None

    def test_create_manual_review_duplicate(self, client, second_user_headers, sample_paper):
        review_data = {"score": 7, "content": "Good.", "recommendation": "accept"}
        client.post(f"/api/papers/{sample_paper['id']}/reviews", json=review_data, headers=second_user_headers)
        resp = client.post(f"/api/papers/{sample_paper['id']}/reviews", json=review_data, headers=second_user_headers)
        assert resp.status_code == 400

    def test_create_manual_review_invalid_score(self, client, second_user_headers, sample_paper):
        resp = client.post(f"/api/papers/{sample_paper['id']}/reviews", json={
            "score": 11, "content": "Bad.", "recommendation": "reject",
        }, headers=second_user_headers)
        assert resp.status_code == 422


class TestListReviews:
    @patch("app.routers.reviews._run_ai_review")
    def test_list_reviews_mixed(self, mock_bg, client, auth_headers, second_user_headers, sample_paper):
        # Create AI review (pending)
        client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        # Create manual review
        client.post(f"/api/papers/{sample_paper['id']}/reviews", json={
            "score": 8, "content": "Good paper.", "recommendation": "accept",
        }, headers=second_user_headers)

        resp = client.get(f"/api/papers/{sample_paper['id']}/reviews", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        sources = {r["source"] for r in data}
        assert sources == {"ai", "manual"}


class TestUpdateReview:
    def test_update_manual_review(self, client, second_user_headers, sample_paper):
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/reviews", json={
            "score": 6, "content": "OK.", "recommendation": "major_revision",
        }, headers=second_user_headers)
        review_id = create_resp.json()["id"]

        resp = client.put(f"/api/reviews/{review_id}", json={"score": 8}, headers=second_user_headers)
        assert resp.status_code == 200
        assert resp.json()["score"] == 8

    @patch("app.routers.reviews._run_ai_review")
    def test_cannot_update_ai_review(self, mock_bg, client, auth_headers, sample_paper):
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        review_id = create_resp.json()["id"]

        resp = client.put(f"/api/reviews/{review_id}", json={"score": 10}, headers=auth_headers)
        assert resp.status_code == 403


class TestDeleteReview:
    def test_delete_manual_review(self, client, second_user_headers, sample_paper):
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/reviews", json={
            "score": 5, "content": "Avg.", "recommendation": "minor_revision",
        }, headers=second_user_headers)
        review_id = create_resp.json()["id"]

        resp = client.delete(f"/api/reviews/{review_id}", headers=second_user_headers)
        assert resp.status_code == 204

    @patch("app.routers.reviews._run_ai_review")
    def test_delete_ai_review(self, mock_bg, client, auth_headers, sample_paper):
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        review_id = create_resp.json()["id"]

        resp = client.delete(f"/api/reviews/{review_id}", headers=auth_headers)
        assert resp.status_code == 204
