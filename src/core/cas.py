# -*- coding: utf-8 -*-
import requests


class __CASApi:
    __URL_CSV = 'https://api.cas.chat/export.csv'
    __URL_CHECK = 'https://api.cas.chat/check?user_id={user_id}'

    def check(self, user_id):
        res = requests.get(self.__URL_CHECK.format(user_id=user_id))
        if res.status_code != 200:
            return {'ok': False, 'description': 'Record not found.'}
        return res.json()


casapi = __CASApi()
