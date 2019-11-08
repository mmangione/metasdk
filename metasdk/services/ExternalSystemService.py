from ..utils import decode_jwt


class ExternalSystemService:
    def __init__(self, app):
        """
        :type app: metasdk.MetaApp
        """
        self.__app = app
        self.__options = {}
        self.__data_get_cache = {}
        self.__data_get_flatten_cache = {}
        self.__metadb = app.db("meta")
        self.__crypt_params = None

    def get_access(self, ex_access_id):
        ex_access = self.__metadb.one(
            """
            SELECT
                ex_system_id, 
                login, 
                token_info,
                form_data 
            FROM meta.ex_access 
            WHERE id=:id::uuid
            """,
            {"id": ex_access_id}
        )

        token_info_ = ex_access.get('token_info')

        if token_info_ and token_info_.get('accessToken'):
            ex_access['token_info']['accessToken'] = decode_jwt(token_info_.get('accessToken'), self.__get_crypt_params()['secureKey'])

        if token_info_ and token_info_.get('refreshToken'):
            ex_access['token_info']['refreshToken'] = decode_jwt(token_info_.get('refreshToken'), self.__get_crypt_params()['secureKey'])

        return ex_access

    def __get_crypt_params(self):
        # lazy load
        if self.__crypt_params is None:
            self.__crypt_params = self.__app.SettingsService.data_get("crypt_params")
        return self.__crypt_params
