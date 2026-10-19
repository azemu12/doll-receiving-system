"""业务条码生成服务（独立模块，不写在 API 接口里）。

条码编码规则（业务约定，禁止擅自修改）：
    0 + 售价十位 + 任意两位数字xx + 成本(两位,补零) + 售价个位

拆解示例：
    售价40、成本18 -> 04xx180   （0 / 4 / xx / 18 / 0）
    售价50、成本18 -> 05xx180   （0 / 5 / xx / 18 / 0）
    售价39、成本18 -> 03xx189   （0 / 3 / xx / 18 / 9）

xx 说明：
    - xx 是 00~99 的两位数字，只是占位，不参与任何价格计算；
    - 第一版每次调用随机生成一个合法的两位数字；
    - 【重要】库存创建时生成一次并保存到 inventory.barcode，之后一律读库原样
      返回，绝不重新生成（否则同一只娃娃每次查看条码都会变）。

当前实现支持的范围（超出范围一律抛 BarcodeError，不擅自发明新规则）：
    - sale_price：0~99 的整数（当前业务所有娃娃售价均为整数，且有十位/个位）；
    - recovery_cost：0~99 的【整数值】。
      可接受 int 18、Decimal("18")、Decimal("18.00")；
      但 Decimal("18.50") 这类带小数的成本，当前规则无法把"角/分"编码进
      两位成本位，会抛 BarcodeError —— 若实际业务出现此类成本，
      需要业务方先明确新规则，再扩展本函数。
"""

import random
from decimal import Decimal


class BarcodeError(ValueError):
    """输入超出当前条码业务规则可编码范围时抛出。"""


def generate_barcode(sale_price: int, recovery_cost) -> str:
    """按业务规则生成 7 位条码字符串。

    参数：
        sale_price:    SKU 固定售价（元），必须是 0~99 的整数。
        recovery_cost: 该只娃娃实际回收成本（元），必须是 0~99 的整数值
                       （int 或整数值的 Decimal）。

    返回：
        形如 "04xx180" 的 7 位字符串，其中 xx 为随机两位数字。

    异常：
        BarcodeError: 售价/成本超出当前规则可编码范围。
    """
    # ---- 售价校验：必须是有十位/个位的整数（0~99）----
    if isinstance(sale_price, bool) or not isinstance(sale_price, int):
        raise BarcodeError(f"售价必须是整数，当前值: {sale_price!r}")
    if not (0 <= sale_price <= 99):
        raise BarcodeError(
            f"当前条码规则仅支持 0~99 元的整数售价，当前售价: {sale_price} 元"
        )

    # ---- 成本校验：必须是 0~99 的整数值 ----
    # 用 str() 中转，避免 float 二进制误差（如 18.1 -> 18.100000...0002）
    cost = recovery_cost if isinstance(recovery_cost, Decimal) else Decimal(str(recovery_cost))
    if cost != cost.to_integral_value():
        raise BarcodeError(
            f"当前条码规则只能编码整数成本（0~99 元），"
            f"无法编码带小数的成本: {cost} 元"
        )
    cost_int = int(cost)
    if not (0 <= cost_int <= 99):
        raise BarcodeError(
            f"当前条码规则仅支持 0~99 元的成本，当前成本: {cost_int} 元"
        )

    price_tens = sale_price // 10
    price_ones = sale_price % 10
    xx = random.randint(0, 99)  # 占位两位，不参与价格计算
    return f"0{price_tens}{xx:02d}{cost_int:02d}{price_ones}"
