from unittest.mock import patch


class TestAiReview:
    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_ai_review_returns_pending(self, mock_delay, client, auth_headers, sample_paper):
        """Endpoint should return a pending review immediately."""
        mock_delay.return_value.id = "task-123"
        resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["paper_id"] == sample_paper["id"]
        assert "review_id" in data
        assert data["task_id"] == "task-123"
        assert data["status"] == "pending"
        mock_delay.assert_called_once()

    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_ai_review_duplicate(self, mock_delay, client, auth_headers, sample_paper):
        mock_delay.return_value.id = "task-123"
        client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        assert resp.status_code == 400

    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_ai_review_updates_paper_status(self, mock_delay, client, auth_headers, sample_paper):
        mock_delay.return_value.id = "task-123"
        client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        resp = client.get(f"/api/papers/{sample_paper['id']}", headers=auth_headers)
        assert resp.json()["status"] == "under_review"

    def test_ai_review_paper_not_found(self, client, auth_headers):
        resp = client.post("/api/papers/9999/ai-review", headers=auth_headers)
        assert resp.status_code == 404

    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_get_review_by_id(self, mock_delay, client, auth_headers, sample_paper):
        mock_delay.return_value.id = "task-123"
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        review_id = create_resp.json()["review_id"]

        resp = client.get(f"/api/reviews/{review_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == review_id
        assert data["status"] == "pending"
        assert data["score"] is None


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
    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_list_reviews_mixed(self, mock_delay, client, auth_headers, second_user_headers, sample_paper):
        mock_delay.return_value.id = "task-123"
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

    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_cannot_update_ai_review(self, mock_delay, client, auth_headers, sample_paper):
        mock_delay.return_value.id = "task-123"
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        review_id = create_resp.json()["review_id"]

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

    @patch("app.routers.reviews.run_ai_review_task.delay")
    def test_delete_ai_review(self, mock_delay, client, auth_headers, sample_paper):
        mock_delay.return_value.id = "task-123"
        create_resp = client.post(f"/api/papers/{sample_paper['id']}/ai-review", headers=auth_headers)
        review_id = create_resp.json()["review_id"]

        resp = client.delete(f"/api/reviews/{review_id}", headers=auth_headers)
        assert resp.status_code == 204
