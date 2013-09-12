from celery.decorators import task
from celery.utils.log import get_task_logger
from recharge.models import Recharge, RechargeError
from celerytasks.models import StoreToken
from django.conf import settings
import requests
import json
import random
import datetime
from django.utils import timezone
from celery.exceptions import MaxRetriesExceededError
from gopherairtime.custom_exceptions import (TokenInvalidError, TokenExpireError,
                                             MSISDNNonNumericError, MSISDMalFormedError,
                                             BadProductCodeError, BadNetworkCodeError,
                                             BadCombinationError, DuplicateReferenceError,
                                             NonNumericReferenceError)

logger = get_task_logger(__name__)

@task
def hotsocket_login():
	data = {
			    "username": settings.HOTSOCKET_USERNAME,
			    "password": settings.HOTSOCKET_PASSWORD,
			    "as_json": True
			}

	url = "%s%s" % (settings.HOTSOCKET_BASE, settings.HOTSOCKET_RESOURCES["login"])
	headers = {'content-type': 'application/json'}
	response = requests.post(url, data=data)
	json_response = response.json()

	if str(json_response["response"]["status"]) == "0000":
		# Assuming the token will always be at primary key one
		updated_at = timezone.now()
		expire_at = updated_at + datetime.timedelta(minutes=settings.TOKEN_DURATION)
		if not StoreToken.objects.filter(id=1).exists():
			store = StoreToken(token=json_response["response"]["token"],
			                   updated_at=updated_at,
			                   expire_at=expire_at,
			                   pk=1)
			store.save()
		else:
			query = StoreToken.objects.get(id=1)
			query.token = json_response["response"]["token"]
			query.updated_at = updated_at
			query.expire_at = expire_at
			query.save()


@task
def run_queries():
	"""
	Main purpose of this is to call functions that query database and to chain them
	"""
	# logger.info("Running database query")
	recharge_query.delay()
	status_query.delay()
	errors_query.delay()


@task
def recharge_query():
	"""
	Queries database and passes it to the get_recharge() task asynchronously
	"""
	try:
		store_token = StoreToken.objects.get(id=1)
		queryset = (Recharge.objects.filter(recharge_system_ref=None).
		            filter(reference=None).all())
		queryset = Recharge.objects.all()

		for query in queryset:
			reference = random.randint(0, 999999999999999)  # reference to be passed with hot socket
			data = {"username": settings.HOTSOCKET_USERNAME,
					"token": store_token.token,
					"recipient_msisdn": query.msisdn,
					"product_code": query.product_code,
					"denomination": query.denomination,  # In cents
					"network_code": "VOD",
					"reference": reference,
					"as_json": True}
			get_recharge.delay(data, query.id)
	except StoreToken.DoesNotExist, exc:
		hotsocket_login.delay()
		recharge_query.retry(countdown=20, exc=exc)


@task
def status_query():
	pass


@task
def errors_query():
	pass


@task()
def get_recharge(data, query_id):
		url = "%s%s" % (settings.HOTSOCKET_BASE, settings.HOTSOCKET_RESOURCES["recharge"])
		headers = {'content-type': 'application/json'}
		code = settings.HOTSOCKET_CODES
		query = Recharge.objects.get(id=query_id)
		try:
			response = requests.post(url, data=data)
			json_response = response.json()
			status = json_response["response"]["status"]
			message = json_response["response"]["message"]
			if str(status) == code["SUCCESS"]["status"]:
				query.reference = data["reference"]
				query.recharge_system_ref = json_response["response"]["hotsocket_ref"]
				query.status = status
				query.save()

			elif status == code["REF_DUPLICATE"]["status"]:
				raise DuplicateReferenceError(message)

			elif status == code["REF_NON_NUM"]["status"]:
				raise NonNumericReferenceError(message)

			elif status == code["TOKEN_EXPIRE"]["status"]:
				raise TokenExpireError(message)

			elif status == code["TOKEN_INVALID"]["status"]:
				raise TokenInvalidError(message)

			elif status == code["MSISDN_NON_NUM"]["status"]:
				raise MSISDNNonNumericError(message)

			elif status == code["MSISDN_MALFORMED"]["status"]:
				raise MSISDMalFormedError(message)

			elif status == code["PRODUCT_CODE_BAD"]["status"]:
				raise BadProductCodeError(message)

			elif status == code["NETWORK_CODE_BAD"]["status"]:
				raise BadNetworkCodeError(message)

			elif status == code["COMBO_BAD"]["status"]:
				raise BadCombinationError(message)


		except (DuplicateReferenceError, NonNumericReferenceError), exc:
			new_reference = random.randint(0, 999999999999999)
			data["reference"] = new_reference
			get_recharge.retry(args=[data, query_id], exc=exc)

		except (TokenInvalidError, TokenExpireError), exc:
			if hotsocket_login.delay().ready():
				store_token = StoreToken.objects.get(id=1)
				data["token"] = store_token.token
				get_recharge.retry(args=[data, query_id], exc=exc)

		except (MSISDNNonNumericError, MSISDMalFormedError, BadProductCodeError,
		        BadNetworkCodeError, BadCombinationError), exc:
			error = RechargeError(error_id=status,
			                      error_message=message,
			                      last_attempt_at=timezone.now(),
			                      recharge_error=query,
			                      tries=1)
			error.save()