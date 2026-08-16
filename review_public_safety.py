# -*- coding: utf-8 -*-
"""面向客服与客户的审核输出脱敏。"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


_IDENTIFIER_PATTERNS = (
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?![\dXx])"),
    re.compile(r"(?<!\d)\d{15}(?!\d)"),
    re.compile(r"(?<!\d)1[3-9](?:[ -]?\d){9}(?!\d)"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]\d{7,9}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"),
)
_LABELED_NAME_PATTERN = re.compile(
    r"((?:申请人姓名|监护人姓名|收件人姓名|申请人|监护人|收件人|姓名)\s*[：:]\s*)[\u4e00-\u9fff·]{2,12}"
)
_LABELED_ADDRESS_PATTERN = re.compile(
    r"((?:收货地址|家庭住址|联系地址|住址|地址)\s*[：:]\s*)[^，,。；;\n]{4,120}"
)
_UNLABELED_NAME_PATTERN = re.compile(
    r"(^|[，,。；;\s])([\u4e00-\u9fff·]{2,4})(?=本人(?:提交|申请|上传|提供))"
)
_CONTEXTUAL_NAME_PATTERN = re.compile(
    r"((?:材料由|联系人|收货人|申请人|监护人|用户姓名|客户姓名)\s*)"
    r"[\u4e00-\u9fff·]{2,12}(?=(?:提交|申请|上传|提供|称|表示|说明|[，,；;。\s]|$))"
)
_PERSON_NAME_PATTERN = (
    r"(?:欧阳|司马|上官|诸葛|东方|皇甫|尉迟|公孙|慕容|令狐|长孙|宇文|司徒|南宫|夏侯|"
    r"[赵钱孙李周吴郑王冯陈蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜谢邹苏潘葛范彭鲁韦马方任袁柳史唐薛雷贺倪汤罗郝安常傅齐康伍余顾孟黄萧尹姚邵汪毛戴宋熊纪舒屈项董梁杜阮蓝季贾江郭梅林钟徐高夏蔡田樊胡霍万卢莫丁邓洪包左石崔龚])"
    r"[\u4e00-\u9fff·]{1,2}"
)
_SPEECH_VERB_PATTERN = (
    r"(?:称|表示|说|反馈|投诉|反映|来电(?:咨询)?|咨询|回复|提到|告知|描述|"
    r"提交|上传|申请|要求|认为|解释|确认|主张|[：:，,])"
)
_CUSTOMER_SPEECH_NAME_PATTERN = re.compile(
    rf"((?:客户|用户)\s*){_PERSON_NAME_PATTERN}\s*(?={_SPEECH_VERB_PATTERN})"
)
_CUSTOMER_NAME_RUN_PATTERN = re.compile(
    rf"((?:客户|用户)\s*){_PERSON_NAME_PATTERN}[\u4e00-\u9fff·]*"
)
_BARE_SPEAKER_NAME_PATTERN = re.compile(
    rf"(^|[，。；;\s]){_PERSON_NAME_PATTERN}(?={_SPEECH_VERB_PATTERN})"
)
_UNLABELED_ADDRESS_PATTERN = re.compile(
    r"((?:住在|居住于|收货到|寄送至|地址为|收货地点为)\s*)[^，,。；;\n]{4,120}"
)
_LABELED_TRACKING_PATTERN = re.compile(
    r"((?:快递面单单号|面单单号|快递单号|物流单号|运单号|面单号)\s*[：:]?\s*)"
    r"[A-Za-z0-9-]{8,32}",
    flags=re.IGNORECASE,
)
_LABELED_ACCOUNT_PATTERN = re.compile(
    r"((?:银行卡号|银行卡|银行账号|卡号|支付账号|收款账号|支付宝账号|微信号|微信账号)\s*[：:]?\s*)"
    r"[A-Za-z0-9@._+-]{5,64}",
    flags=re.IGNORECASE,
)


def _is_public_media_url(value: str) -> bool:
    path = urlsplit(value).path
    return bool(
        re.fullmatch(r"/media-item/[a-f0-9]{32}", path)
        or re.fullmatch(r"/api/v1/review/jobs/[^/]+/media/[a-f0-9]{32}", path)
        or re.fullmatch(r"/reports/[a-zA-Z0-9._-]+\.html", path)
    )


def redact_public_review_data(value: Any) -> Any:
    """递归脱敏模型自由文本，同时保留受控媒体跳转地址。"""
    if isinstance(value, dict):
        return {str(key): redact_public_review_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_public_review_data(item) for item in value]
    if not isinstance(value, str) or _is_public_media_url(value):
        return value
    output = value
    for pattern in _IDENTIFIER_PATTERNS:
        output = pattern.sub("[已脱敏]", output)
    output = _LABELED_NAME_PATTERN.sub(r"\1[已脱敏]", output)
    output = _LABELED_ADDRESS_PATTERN.sub(r"\1[已脱敏]", output)
    output = _UNLABELED_NAME_PATTERN.sub(r"\1[已脱敏]", output)
    output = _CONTEXTUAL_NAME_PATTERN.sub(r"\1[已脱敏]", output)
    output = _CUSTOMER_SPEECH_NAME_PATTERN.sub(r"\1[已脱敏]", output)
    output = _CUSTOMER_NAME_RUN_PATTERN.sub(r"\1[已脱敏]", output)
    output = _BARE_SPEAKER_NAME_PATTERN.sub(r"\1[已脱敏]", output)
    output = _UNLABELED_ADDRESS_PATTERN.sub(r"\1[已脱敏]", output)
    output = _LABELED_TRACKING_PATTERN.sub(r"\1[已脱敏]", output)
    return _LABELED_ACCOUNT_PATTERN.sub(r"\1[已脱敏]", output)
