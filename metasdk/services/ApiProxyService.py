import json
import time
import copy

import requests

from metasdk.logger import LOGGER_ENTITY
from metasdk.exceptions import RetryHttpRequestError, EndOfTriesError, UnexpectedError, ApiProxyError


class ApiProxyService:

    MAX_PAGES = 100000

    def __init__(self, app, default_headers):
        """
        :type app: metasdk.MetaApp
        """
        self.__app = app
        self.__default_headers = default_headers
        self.__options = {}
        self.__data_get_cache = {}
        self.__data_get_flatten_cache = {}

    def __api_proxy_call(self, engine, payload, method, analyze_json_error_param, retry_request_substr_variants,
                         stream=False):
        """
        :param engine: Система
        :param payload: Данные для запроса
        :param method: string Может содержать native_call | tsv | json_newline
        :param analyze_json_error_param: Нужно ли производить анализ параметра error в ответе прокси
        :param retry_request_substr_variants: Список подстрок, при наличии которых в ответе будет происходить перезапрос
        :param stream:
        :return:
        """
        log_ctx = {
            "engine": engine,
            "method": payload.get('method'),
            "method_params": payload.get('method_params')
        }
        self.__app.log.info("Call api proxy", log_ctx)
        body = {
            "engine": engine,
            "payload": payload
        }
        for _try_idx in range(20):
            try:
                # 1h таймаут, так как бывают большие долгие данные, а лимит хоть какой-то нужен
                body_str = json.dumps(body)
                headers = {
                    "User-Agent": self.__app.user_agent,
                    "X-App": "META",
                    "X-Worker": self.__app.service_id,
                    "X-ObjectLocator": LOGGER_ENTITY.get("objectLocator")
                }
                resp = requests.post(self.__app.api_proxy_url + "/" + method, body_str, timeout=3600, stream=stream,
                                     headers=headers)

                self.check_err(resp, analyze_json_error_param=analyze_json_error_param,
                               retry_request_substr_variants=retry_request_substr_variants)
                return resp
            except RetryHttpRequestError as e:
                self.__app.log.warning("Sleep retry query: " + str(e), log_ctx)
                time.sleep(20)
        raise EndOfTriesError("Api of api proxy tries request")

    def call_proxy_with_paging(self, engine, payload, method, analyze_json_error_param, retry_request_substr_variants,
                               max_pages=MAX_PAGES):
        """
        Постраничный запрос
        :param engine: Система
        :param payload: Данные для запроса
        :param method: string Может содержать native_call | tsv | json_newline
        :param analyze_json_error_param: Нужно ли производить анализ параметра error в ответе прокси
        :param retry_request_substr_variants: Список подстрок, при наличии которых в ответе будет происходить перезапрос
        :return: объект генератор
        """
        copy_payload = copy.deepcopy(payload)

        for _ in range(max_pages):
            resp = self.__api_proxy_call(engine, copy_payload, method, analyze_json_error_param,
                                         retry_request_substr_variants)
            yield resp

            paging_resp = resp.json().get("paging")
            if not paging_resp:
                break
            copy_payload["paging"] = paging_resp

        self.__app.log.warning("Достигнут максимальный предел страниц", {"max_pages": max_pages})

    def call_proxy(self, engine, payload, method, analyze_json_error_param, retry_request_substr_variants,
                   stream=False):
        """
        :param engine: Система
        :param payload: Данные для запроса
        :param method: string Может содержать native_call | tsv | json_newline
        :param analyze_json_error_param: Нужно ли производить анализ параметра error в ответе прокси
        :param retry_request_substr_variants: Список подстрок, при наличии которых в ответе будет происходить перезапрос
        :param stream:
        :return:
        """
        return self.__api_proxy_call(engine, payload, method, analyze_json_error_param, retry_request_substr_variants,
                                     stream)

    @staticmethod
    def check_err(resp, analyze_json_error_param=False, retry_request_substr_variants=None):
        """
        :type retry_request_substr_variants: list Список вхождений строк, при налиции которых в ошидке апи будет произведен повторный запрос к апи
        """
        if retry_request_substr_variants is None:
            retry_request_substr_variants = []

        # РКН блокировки вызывают ошибку SSL
        retry_request_substr_variants.append("TLSV1_ALERT_ACCESS_DENIED")

        if resp.status_code in [502, 503, 504]:
            raise RetryHttpRequestError(resp.text)

        if resp.status_code >= 400:
            rtext = resp.text
            for v_ in retry_request_substr_variants:
                if v_ in rtext:
                    raise RetryHttpRequestError(rtext)
            raise UnexpectedError("HTTP request failed: {} {}".format(resp.status_code, rtext))
        if analyze_json_error_param:
            data_ = resp.json()
            if 'error' in data_ and data_.get('error'):
                full_err_ = json.dumps(data_.get('error'))
                for v_ in retry_request_substr_variants:
                    if v_ in full_err_:
                        raise RetryHttpRequestError(full_err_)
                raise ApiProxyError(full_err_)
        return resp
