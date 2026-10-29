from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from webapp.api.agent_tasks import AgentTaskManager
from webapp.api.store import JobStore
from webapp.auth.service import AuthService, AuthenticationError
from webapp.auth.store import AuthStore
from webapp.execution_context import AgentTargetError, verified_agent_id
from webapp.workspaces.paths import UserDataPaths
from local_agent.client import AgentApiClient, AgentApiError
from local_agent.paths import load_or_create_agent_id, regenerate_agent_id

A, B = 'a' * 32, 'b' * 32
ORIGIN = 'https://console.example'


@contextmanager
def target(agent_id):
    marker = verified_agent_id.set(agent_id)
    try:
        yield
    finally:
        verified_agent_id.reset(marker)


class ExecutionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.paths = UserDataPaths.create(Path(self.directory.name), 'c' * 32)
        self.store = JobStore(self.paths.runtime)
        self.manager = AgentTaskManager(self.store, user_id='c' * 32, paths=self.paths)
        self.connect(A)

    def tearDown(self):
        self.manager.shutdown()
        self.directory.cleanup()

    def connect(self, agent_id):
        self.manager.connect_agent(agent_id=agent_id, device_name=agent_id[:1], system='test', version='test')

    def queued(self, account='shop1', **kwargs):
        return self.store.create_job(kind='publish', platform='jd', account=account,
            payload={'target_agent_id':A,'target_binding_id':A,'managed_upload':False,**kwargs})

    def test_an_online_device_does_not_prove_browser_device_ownership(self):
        with self.assertRaises(AgentTargetError):
            self.manager.submit_account_task(kind='login', platform='jd', account='shop')

    def test_proof_requires_matching_device_origin_and_one_time_challenge(self):
        challenge = self.manager.issue_identity_challenge(origin=ORIGIN)
        with self.assertRaises(AgentTargetError):
            self.manager.verify_identity_proof(challenge['ticket'], origin=ORIGIN)
        with self.assertRaises(PermissionError):
            self.manager.confirm_identity_challenge(ticket=challenge['ticket'], agent_id=B, origin=ORIGIN)
        with self.assertRaises(PermissionError):
            self.manager.confirm_identity_challenge(ticket=challenge['ticket'], agent_id=A, origin='https://other.example')
        proof = self.manager.confirm_identity_challenge(ticket=challenge['ticket'], agent_id=A, origin=ORIGIN)
        self.assertEqual(self.manager.verify_identity_proof(proof['proof'], origin=ORIGIN), A)
        with self.assertRaises(AgentTargetError):
            self.manager.confirm_identity_challenge(ticket=challenge['ticket'], agent_id=A, origin=ORIGIN)
        self.manager._identity_proofs[proof['proof']]['expires_at'] = 0
        with self.assertRaises(AgentTargetError):
            self.manager.verify_identity_proof(proof['proof'], origin=ORIGIN)

    def test_task_is_not_transferred_when_online_device_changes(self):
        with target(A):
            job = self.manager.submit_account_task(kind='login', platform='jd', account='shop')
        self.manager.disconnect_all_agents()
        self.connect(B)
        self.assertIsNone(self.manager.claim_next_job(B))
        self.assertEqual(self.store.get_job(job['id'])['status'], 'queued')

    def test_same_device_id_with_new_pairing_cannot_inherit_old_tasks_or_proofs(self):
        with target(A):
            job = self.manager.submit_account_task(kind='login', platform='jd', account='shop')
        challenge = self.manager.issue_identity_challenge(origin=ORIGIN)
        proof = self.manager.confirm_identity_challenge(ticket=challenge['ticket'], agent_id=A, origin=ORIGIN)
        self.manager.connect_agent(agent_id=A, device_name='replacement', system='test', version='test', binding_id='new-binding')
        with self.assertRaises(AgentTargetError):
            self.manager.verify_identity_proof(proof['proof'], origin=ORIGIN)
        self.assertIsNone(self.manager.claim_next_job(A))
        self.assertEqual(self.store.get_job(job['id'])['status'], 'queued')

    def test_unbound_legacy_queue_is_not_assigned_to_current_device(self):
        job = self.store.create_job(kind='login', platform='jd', account='shop', payload={})
        self.assertIsNone(self.manager.claim_next_job(A))
        self.assertEqual(self.store.get_job(job['id'])['status'], 'failed')

    def test_heartbeat_download_and_completion_verify_target_as_well_as_claim(self):
        job = self.queued()
        self.manager.claim_next_job(A)
        self.store.update_job(job['id'], payload={'target_agent_id':B})
        with self.assertRaises(PermissionError):
            self.manager.heartbeat(job['id'], A)
        with self.assertRaises(PermissionError):
            self.manager.get_claimed_job(job['id'], A)
        with self.assertRaises(PermissionError):
            self.manager.complete_agent_job(job['id'], A, status='succeeded', message='', error='', result={}, logs=[])

    def test_frequency_pause_persists_and_only_blocks_publishing_for_that_account(self):
        failed = self.queued('shop1')
        waiting = self.queued('shop1')
        other = self.queued('shop2')
        self.manager.claim_next_job(A)
        self.manager.complete_agent_job(failed['id'], A, status='failed', message='', error='',
            result={'pause_account':True,'pause_reason':'rate_limited'}, logs=[])
        self.assertEqual(self.manager.claim_next_job(A)['id'], other['id'])
        self.manager.complete_agent_job(other['id'], A, status='succeeded', message='', error='', result={}, logs=[])
        self.assertIsNone(self.manager.claim_next_job(A))
        self.manager.shutdown()
        self.store = JobStore(self.paths.runtime)
        self.manager = AgentTaskManager(self.store, user_id='c'*32, paths=self.paths)
        self.connect(A)
        self.assertIsNone(self.manager.claim_next_job(A))
        with self.assertRaises(AgentTargetError):
            self.manager.resume_account('jd', 'shop1')
        with target(A):
            self.manager.resume_account('jd', 'shop1')
        self.assertEqual(self.manager.claim_next_job(A)['id'], waiting['id'])


class PairingOwnershipTests(unittest.TestCase):
    def test_collision_preserves_both_users_tokens_and_does_not_consume_code(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(Path(directory)/'auth.db')
            first = store.create_user(username='first_user', display_name='first', password_hash='test', role='operator')
            second = store.create_user(username='second_user', display_name='second', password_hash='test', role='operator')
            service = AuthService(store)
            def pair(user, agent_id, code=None):
                code = code or service.issue_agent_pairing_code(user_id=user.id, ip_address='test')[0]
                return service.pair_agent(pairing_code=code, agent_id=agent_id, device_name='test', system='test', version='1', ip_address='test')
            _, first_token = pair(first, A)
            _, second_token = pair(second, B)
            code, _ = service.issue_agent_pairing_code(user_id=second.id, ip_address='test')
            with self.assertRaises(AuthenticationError):
                pair(second, A, code)
            self.assertIsNotNone(service.resolve_agent(first_token))
            self.assertIsNotNone(service.resolve_agent(second_token))
            replacement, _ = pair(second, 'd'*32, code)
            self.assertEqual(replacement.user.id, second.id)

    def test_cloned_local_device_identifier_can_be_explicitly_regenerated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = load_or_create_agent_id(root)
            replacement = regenerate_agent_id(root)
            self.assertNotEqual(previous, replacement)
            self.assertEqual(load_or_create_agent_id(root), replacement)

    def test_helper_rejects_wrong_user_or_target_before_returning_claimed_job(self):
        client = AgentApiClient('https://console.example')
        client.user = {'id':A}
        client.binding_id = 'binding-A'
        for user, agent in [(B,A),(A,B),(None,A)]:
            with self.subTest(user=user, agent=agent):
                client.request_json = Mock(return_value={'job':{'user_id':user,'payload':{'target_agent_id':agent,'target_binding_id':'binding-A'}}})
                with self.assertRaises(AgentApiError):
                    client.claim(A)
        correct = {'user_id':A,'payload':{'target_agent_id':A,'target_binding_id':'binding-A'}}
        client.request_json = Mock(return_value={'job':correct})
        self.assertEqual(client.claim(A), correct)
