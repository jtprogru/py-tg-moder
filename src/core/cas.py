# -*- coding: utf-8 -*-
import requests

# Network timeout (connect, read) in seconds for CAS API calls.
REQUEST_TIMEOUT = (5, 10)


class __CASApi:
    __URL_CSV = "https://api.cas.chat/export.csv"
    __URL_CHECK = "https://api.cas.chat/check?user_id={user_id}"

    def check(self, user_id):
        try:
            res = requests.get(self.__URL_CHECK.format(user_id=user_id), timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            # Fail open: on any network error treat the user as not listed
            # so we don't ban legitimate newcomers because CAS is unreachable.
            return {"ok": False, "description": "Record not found."}
        if res.status_code != 200:
            return {"ok": False, "description": "Record not found."}
        try:
            return res.json()
        except ValueError:
            # A 200 with a malformed body must not crash the join flow; fail
            # open like the network-error case above.
            return {"ok": False, "description": "Record not found."}


casapi = __CASApi()
