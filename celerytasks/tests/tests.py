from django.test import TestCase
from django.test.utils import override_settings
from django.conf import settings
import random
import requests
from recharge.models import Recharge, RechargeError
from celerytasks.models import StoreToken
from celerytasks.tasks import (run_queries, hotsocket_login, get_recharge,
                               balance_query, balance_checker, send_kato_im_threshold_warning,
                               send_pushover_threshold_warning)
from gopherairtime.custom_exceptions import (TokenInvalidError, TokenExpireError,
                                             MSISDNNonNumericError, MSISDMalFormedError,
                                             BadProductCodeError, BadNetworkCodeError,
                                             BadCombinationError, DuplicateReferenceError,
                                             NonNumericReferenceError)
from mock import patch, Mock
from users.models import GopherAirtimeAccount


code = settings.HOTSOCKET_CODES

def my_side_effect(*args, **kwargs):
    m = Mock()
    NET_CODE = ["VOD", "MTN", "CELLC", "8TA"]
    PROD_CODE = ["AIRTIME", "DATA", "SMS"]

    if "data" in kwargs:
        if ("username" and "password") in kwargs["data"]:
            m.json.return_value = {"response": {"status": "0000", "token": "123456789"}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and  (isinstance(kwargs["data"]["token"], str)):
            m.json.return_value = {"response": {"status": code["TOKEN_INVALID"]["status"],
                                    "message": code["TOKEN_INVALID"]["message"]}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and (isinstance(kwargs["data"]["reference"], str)):
            m.json.return_value = {"response": {"status": code["REF_NON_NUM"]["status"],
                                    "message": code["REF_NON_NUM"]["message"]}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and (kwargs["data"]["reference"] == 10):
            m.json.return_value = {"response": {"status": code["REF_DUPLICATE"]["status"],
                                    "message": code["REF_DUPLICATE"]["message"]}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and (isinstance(kwargs["data"]["recipient_msisdn"], str)):
            m.json.return_value = {"response": {"status": code["MSISDN_NON_NUM"]["status"],
                                    "message": code["MSISDN_NON_NUM"]["message"]}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and (kwargs["data"]["network_code"] not in NET_CODE):
            m.json.return_value = {"response": {"status": code["NETWORK_CODE_BAD"]["status"],
                                    "message": code["NETWORK_CODE_BAD"]["message"]}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and (kwargs["data"]["product_code"] not in PROD_CODE):
            m.json.return_value = {"response": {"status": code["PRODUCT_CODE_BAD"]["status"],
                                    "message": code["PRODUCT_CODE_BAD"]["message"]}}
            return m

        elif ("token" and "recipient_msisdn") in kwargs["data"] and (len(str(kwargs["data"]["recipient_msisdn"])) < len("27721231234")):
            m.json.return_value = {"response": {"status": code["MSISDN_MALFORMED"]["status"],
                                    "message": code["MSISDN_MALFORMED"]["message"]}}
            return m

        elif (("recipient_msisdn" and "product_code" in kwargs["data"]) and
              (isinstance(kwargs["data"]["reference"], long)) and
              (isinstance(kwargs["data"]["recipient_msisdn"], long))):
            m.json.return_value = {"response": {"status": code["SUCCESS"]["status"],
                                    "message": code["SUCCESS"]["message"],
                                   "hotsocket_ref": "12345"}}
            return m


class TestRecharge(TestCase):
    fixtures = ["test_auth_users.json", "test_projects.json", "test_recharge.json"]

    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True,
                       CELERY_ALWAYS_EAGER = True,
                       BROKER_BACKEND = 'memory',)

    def setUp(self):
        patcher = patch('requests.post', Mock(side_effect=my_side_effect))
        self.MockClass = patcher.start()
        self.addCleanup(patcher.stop)

    def test_requests_post_is_patched(self):
        self.assertEqual(requests.post, self.MockClass)

    def test_data_loaded(self):
        query = Recharge.objects.all()
        self.assertEqual(len(query), 2)

#     def test_query_function(self):
#         run_queries.delay()
#         query = Recharge.objects.all()
#         [self.assertEqual(obj.status, settings.HS_RECHARGE_STATUS_CODES["PENDING"]["code"]) for obj in query]
#         [self.assertIsNotNone(obj.reference) for obj in query]
#         [self.assertIsNotNone(obj.recharge_system_ref) for obj in query]


    def test_recharge_success(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)
        reference = random.randint(0, 999999999999999)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": query.msisdn,
                "product_code": query.product_code,
                "denomination": query.denomination,  # In cents
                "network_code": "VOD",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query.id)
        query = Recharge.objects.get(msisdn=27821231232)
        self.assertIsNotNone(query.reference)
        self.assertIsNotNone(query.recharge_system_ref)
        self.assertEqual(settings.HS_RECHARGE_STATUS_CODES["PENDING"]["code"], query.status)

    def test_invalid_token(self):
        reference = random.randint(0, 999999999999999)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": "x",
                "recipient_msisdn": query.msisdn,
                "product_code": query.product_code,
                "denomination": query.denomination,  # In cents
                "network_code": "VOD",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query.id)
        query = Recharge.objects.get(msisdn=27821231232)
        self.assertIsNotNone(query.reference)
        self.assertIsNotNone(query.recharge_system_ref)
        self.assertEqual(settings.HS_RECHARGE_STATUS_CODES["PENDING"]["code"], query.status)

    def test_duplicate_reference(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)

        query_3 = Recharge.objects.get(msisdn=27821231231)

        self.assertIsNone(query_3.recharge_system_ref)

        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": query_3.msisdn,
                "product_code": query_3.product_code,
                "denomination": query_3.denomination,  # In cents
                "network_code": "VOD",
                "reference": 10,
                "as_json": True}
        get_recharge.delay(data, query_3.id)
        query = Recharge.objects.get(msisdn=27821231231)
        self.assertIsNone(query.recharge_system_ref)

        error = RechargeError.objects.get(recharge_error=query.id)
        self.assertEqual(error.error_id, settings.HOTSOCKET_CODES["REF_DUPLICATE"]["status"])
        self.assertIsNotNone(error.last_attempt_at)

    def test_non_numeric_reference(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)
        reference = "a"
        query_1 = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query_1.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": query_1.msisdn,
                "product_code": query_1.product_code,
                "denomination": query_1.denomination,  # In cents
                "network_code": "VOD",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query_1.id)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        error = RechargeError.objects.get(recharge_error=query.id)
        self.assertEqual(error.error_id, settings.HOTSOCKET_CODES["REF_NON_NUM"]["status"])
        self.assertIsNotNone(error.last_attempt_at)

    def test_non_numeric_msisdn(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)
        reference = random.randint(0, 999999999999999)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": "a",
                "product_code": query.product_code,
                "denomination": query.denomination,  # In cents
                "network_code": "VOD",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query.id)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        error = RechargeError.objects.get(recharge_error=query.id)
        self.assertEqual(error.error_id, settings.HOTSOCKET_CODES["MSISDN_NON_NUM"]["status"])
        self.assertEqual(error.error_message, settings.HOTSOCKET_CODES["MSISDN_NON_NUM"]["message"])
        self.assertIsNotNone(error.last_attempt_at)

    def test_malformed_msisdn(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)
        reference = random.randint(0, 999999999999999)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": 278,
                "product_code": query.product_code,
                "denomination": query.denomination,  # In cents
                "network_code": "VOD",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query.id)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        error = RechargeError.objects.get(recharge_error=query.id)
        self.assertEqual(error.error_id, settings.HOTSOCKET_CODES["MSISDN_MALFORMED"]["status"])
        self.assertEqual(error.error_message, settings.HOTSOCKET_CODES["MSISDN_MALFORMED"]["message"])
        self.assertIsNotNone(error.last_attempt_at)

    def test_bad_product_code(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)
        reference = random.randint(0, 999999999999999)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": query.msisdn,
                "product_code": "GOPHER",
                "denomination": query.denomination,  # In cents
                "network_code": "VOD",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query.id)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        error = RechargeError.objects.get(recharge_error=query.id)
        self.assertEqual(error.error_id, settings.HOTSOCKET_CODES["PRODUCT_CODE_BAD"]["status"])
        self.assertEqual(error.error_message, settings.HOTSOCKET_CODES["PRODUCT_CODE_BAD"]["message"])
        self.assertIsNotNone(error.last_attempt_at)


    def test_bad_network_code(self):
        hotsocket_login()
        store_token = StoreToken.objects.get(id=1)
        reference = random.randint(0, 999999999999999)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        data = {"username": settings.HOTSOCKET_USERNAME,
                "token": store_token.token,
                "recipient_msisdn": query.msisdn,
                "product_code": query.product_code,
                "denomination": query.denomination,  # In cents
                "network_code": "GOPHER",
                "reference": reference,
                "as_json": True}
        get_recharge.delay(data, query.id)
        query = Recharge.objects.get(msisdn=27821231232)

        self.assertIsNone(query.recharge_system_ref)
        error = RechargeError.objects.get(recharge_error=query.id)
        self.assertEqual(error.error_id, settings.HOTSOCKET_CODES["NETWORK_CODE_BAD"]["status"])
        self.assertEqual(error.error_message, settings.HOTSOCKET_CODES["NETWORK_CODE_BAD"]["message"])
        self.assertIsNotNone(error.last_attempt_at)




class TestLogin(TestCase):
    fixtures = ["test_auth_users.json", "test_users.json", "test_recharge.json"]

    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True,
                       CELERY_ALWAYS_EAGER = True,
                       BROKER_BACKEND = 'memory',)

    def setUp(self):
        patcher = patch('requests.post', Mock(side_effect=my_side_effect))
        self.MockClass = patcher.start()
        self.addCleanup(patcher.stop)

    def test_requests_post_is_patched(self):
        self.assertEqual(requests.post, self.MockClass)

    def test_data_loaded(self):
        query = Recharge.objects.all()
        self.assertEqual(len(query), 2)


    def test_query_function(self):
        hotsocket_login()
        query = StoreToken.objects.all()
        [self.assertIsNotNone(obj.token) for obj in query]
        [self.assertIsNotNone(obj.updated_at) for obj in query]
        [self.assertIsNotNone(obj.expire_at) for obj in query]


# class TestBalanceQuery(TestCase):
#     @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True,
#                        CELERY_ALWAYS_EAGER = True,
#                        BROKER_BACKEND = 'memory',)

#     def test_balance_query(self):
#         balance_checker.delay()
#         account = GopherAirtimeAccount.objects.all()
#         self.assertEqual(type(account[0].running_balance), type(1))
#         self.assertIsNotNone(account[0].created_at)

    # def test_kato_im(self):
    #     send_kato_im_threshold_warning.delay(110)

    # def test_pushover(self):
    #     send_pushover_threshold_warning.delay(110)
