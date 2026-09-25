import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import post_to_instagram as p


class RecoveryTests(unittest.TestCase):
    def test_existing_owned_comment_on_second_page_is_not_duplicated(self):
        pages = [{"data": [{"id": "other", "text": p.FIRST_COMMENT, "from": {"id": "other"}}],
                  "paging": {"next": "ignored", "cursors": {"after": "cursor"}}},
                 {"data": [{"id": "ours", "text": p.FIRST_COMMENT, "from": {"id": "account"}}]}]
        with patch.object(p, "graph_get", side_effect=pages) as get, patch.object(p, "post_first_comment") as post:
            self.assertEqual(p.ensure_first_comment("media", "token", "account"), "ours")
            post.assert_not_called()
            self.assertEqual(get.call_args.args[2]["after"], "cursor")

    def test_comment_read_failure_never_attempts_write(self):
        with patch.object(p, "graph_get", side_effect=RuntimeError("denied")), patch.object(p.requests, "post") as post:
            with self.assertRaises(RuntimeError):
                p.ensure_first_comment("media", "token", "account")
            post.assert_not_called()

    def test_missing_comment_is_created_and_read_back(self):
        response = Mock(ok=True)
        response.json.return_value = {"id": "new-comment"}
        with patch.object(p, "graph_get", side_effect=[{"data": []}, {"id": "new-comment", "text": p.FIRST_COMMENT}]) as get, patch.object(p.requests, "post", return_value=response) as post:
            self.assertEqual(p.ensure_first_comment("media", "token", "account"), "new-comment")
            self.assertEqual(post.call_count, 1)
            self.assertEqual(get.call_args.args[0], "new-comment")

    def test_timeout_does_not_retry_comment_write(self):
        with patch.object(p.requests, "post", side_effect=p.requests.Timeout("uncertain")) as post:
            with self.assertRaisesRegex(RuntimeError, "do not republish"):
                p.post_first_comment("media", "token")
            self.assertEqual(post.call_count, 1)

    def test_permission_failure_stops_before_recovery_or_publish(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": {"is_valid": True, "scopes": ["instagram_basic"]}}
        with patch.dict(os.environ, {"INSTAGRAM_ACCESS_TOKEN": "token", "IG_USER_ID": "account"}), patch.object(p.requests, "get", return_value=response), patch.object(p, "repair_recent_comments") as repair, patch.object(p.requests, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "instagram_manage_comments"):
                p.main()
            repair.assert_not_called()
            post.assert_not_called()

    def test_comments_only_never_checks_plan_or_publishes(self):
        with patch.dict(os.environ, {"INSTAGRAM_ACCESS_TOKEN": "token", "IG_USER_ID": "account", "IG_COMMENTS_ONLY": "1"}), patch.object(p, "require_comment_permission"), patch.object(p, "repair_recent_comments") as repair, patch.object(p, "load_plan") as plan, patch.object(p.requests, "post") as post:
            p.main()
            repair.assert_called_once_with("token", "account")
            plan.assert_not_called()
            post.assert_not_called()

    def test_recovery_runs_before_daily_guard(self):
        order = []
        with patch.dict(os.environ, {"INSTAGRAM_ACCESS_TOKEN": "token", "IG_USER_ID": "account", "IG_COMMENTS_ONLY": "", "IG_FORCE": ""}), patch.object(p, "require_comment_permission"), patch.object(p, "repair_recent_comments", side_effect=lambda *a: order.append("repair")), patch.object(p, "already_posted_today", side_effect=lambda *a: order.append("guard") or "today"), patch.object(p.requests, "post") as post:
            p.main()
            self.assertEqual(order, ["repair", "guard"])
            post.assert_not_called()

    def test_recovery_ignores_old_and_unrelated_posts(self):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        media = [{"id": "old", "timestamp": "2026-09-19T00:00:00+0000", "caption": "#USvsChina"},
                 {"id": "unrelated", "timestamp": recent, "caption": "Another product"},
                 {"id": "campaign", "timestamp": recent, "caption": "#USvsChina"}]
        with patch.object(p, "graph_items", return_value=iter(media)), patch.object(p, "ensure_first_comment") as ensure:
            p.repair_recent_comments("token", "account")
            ensure.assert_called_once_with("campaign", "token", "account")
