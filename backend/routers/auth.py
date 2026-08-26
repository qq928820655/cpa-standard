"""
登录认证路由
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.admin_session import AdminSession
from models.admin_user import AdminUser

router = APIRouter()

# 登录配置文件路径
_LOGIN_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "login_config.json"


def _read_login_config() -> dict:
    """读取登录配置"""
    if _LOGIN_CONFIG_PATH.exists():
        try:
            return json.loads(_LOGIN_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"login_enabled": False}


def _write_login_config(config: dict):
    """写入登录配置"""
    _LOGIN_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOGIN_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------- Pydantic 模型 ---------------

class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class LoginConfigRequest(BaseModel):
    login_enabled: bool


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: str | None = None
    username: str | None = None
    role: str | None = None
    api_key: str | None = None


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    username: str
    password: str
    supported_models: list[str] | None = None
    show_image_square: bool = False
    supported_image_models: list[str] | None = None
    daily_token_limit: int | None = None
    weekly_token_limit: int | None = None
    monthly_token_limit: int | None = None
    quota_exceeded_mode: str | None = None
    quota_exceeded_message: str | None = None
    model_mapping: dict[str, Any] | None = None
    show_quota_to_user: bool = False


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    username: str | None = None
    password: str | None = None
    role: str | None = None
    supported_models: list[str] | None = None
    show_image_square: bool | None = None
    supported_image_models: list[str] | None = None
    daily_token_limit: int | None = None
    weekly_token_limit: int | None = None
    monthly_token_limit: int | None = None
    clear_daily_limit: bool = False
    clear_weekly_limit: bool = False
    clear_monthly_limit: bool = False
    quota_exceeded_mode: str | None = None
    quota_exceeded_message: str | None = None
    model_mapping: dict[str, Any] | None = None
    show_quota_to_user: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    username: str
    role: str
    api_key: str | None
    supported_models: list[str]
    show_image_square: bool
    supported_image_models: list[str]
    daily_token_limit: int | None
    weekly_token_limit: int | None
    monthly_token_limit: int | None
    quota_exceeded_mode: str | None
    quota_exceeded_message: str | None
    model_mapping: dict[str, Any]
    show_quota_to_user: bool
    lifetime_request_count: int = 0
    lifetime_success_count: int = 0
    lifetime_error_count: int = 0
    lifetime_prompt_tokens: int = 0
    lifetime_completion_tokens: int = 0
    lifetime_total_tokens: int = 0
    lifetime_cache_tokens: int = 0
    created_at: datetime | None


class RegenerateKeyResponse(BaseModel):
    success: bool
    api_key: str


# --------------- 辅助函数 ---------------

def _parse_supported_models(raw: str | None) -> list[str]:
    """解析 supported_models JSON 字段"""
    if not raw:
        return []
    try:
        models = json.loads(raw)
        if isinstance(models, list):
            return [str(m) for m in models if m]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _parse_model_mapping(raw: str | None) -> dict:
    """解析 model_mapping JSON 字段"""
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
        if isinstance(mapping, dict):
            # value 可以是字符串（直接映射）或列表（阶梯映射），保留原始类型
            return {str(k): v for k, v in mapping.items() if k and v is not None}
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _user_to_response(user: AdminUser) -> UserResponse:
    """将 AdminUser 转换为 UserResponse"""
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role or "user",
        api_key=user.api_key,
        supported_models=_parse_supported_models(user.supported_models),
        show_image_square=bool(getattr(user, "show_image_square", False)),
        supported_image_models=_parse_supported_models(getattr(user, "supported_image_models", None)),
        daily_token_limit=getattr(user, "daily_token_limit", None),
        weekly_token_limit=getattr(user, "weekly_token_limit", None),
        monthly_token_limit=getattr(user, "monthly_token_limit", None),
        quota_exceeded_mode=getattr(user, "quota_exceeded_mode", None) or "normal",
        quota_exceeded_message=getattr(user, "quota_exceeded_message", None),
        model_mapping=_parse_model_mapping(getattr(user, "model_mapping", None)),
        show_quota_to_user=bool(getattr(user, "show_quota_to_user", False)),
        lifetime_request_count=int(getattr(user, "request_count", 0) or 0),
        lifetime_success_count=int(getattr(user, "success_count", 0) or 0),
        lifetime_error_count=int(getattr(user, "error_count", 0) or 0),
        lifetime_prompt_tokens=int(getattr(user, "prompt_tokens", 0) or 0),
        lifetime_completion_tokens=int(getattr(user, "completion_tokens", 0) or 0),
        lifetime_total_tokens=int(getattr(user, "total_tokens", 0) or 0),
        lifetime_cache_tokens=int(getattr(user, "cache_tokens", 0) or 0),
        created_at=user.created_at,
    )


async def _get_user_from_token(authorization: str, db: AsyncSession) -> AdminUser:
    """从 Authorization header 解析 session token 并返回用户"""
    token = authorization.replace("Bearer ", "").strip()
    result = await db.execute(
        select(AdminSession).where(AdminSession.token == token)
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    if session.is_expired():
        await db.delete(session)
        await db.commit()
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    result = await db.execute(
        select(AdminUser).where(AdminUser.id == session.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    # 滑动续期
    from datetime import timedelta
    session.expires_at = datetime.utcnow() + timedelta(days=7)
    await db.commit()

    return user


async def get_current_user_info(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """通用认证依赖：返回当前用户信息，支持 master key 和 session token

    返回: {"is_admin": bool, "user_id": int|None, "user": AdminUser|None}
    """
    from config import settings

    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")

    token = authorization.replace("Bearer ", "").strip()

    # 优先检查 master key
    if token == settings.master_key:
        return {"is_admin": True, "user_id": None, "user": None}

    # 检查 session token
    user = await _get_user_from_token(authorization, db)
    return {
        "is_admin": user.is_admin,
        "user_id": user.id,
        "user": user,
    }


async def _require_admin(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """要求管理员权限，返回 admin 用户对象"""
    info = await get_current_user_info(authorization, db)
    if not info["is_admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return info["user"]


# --------------- 认证端点 ---------------

@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    """检查认证状态：是否开启登录、是否已初始化账户"""
    config = _read_login_config()
    login_enabled = config.get("login_enabled", False)

    result = await db.execute(select(AdminUser).limit(1))
    user = result.scalar_one_or_none()
    initialized = user is not None

    return {
        "login_enabled": login_enabled,
        "initialized": initialized,
        "username": user.username if user else None,
    }


@router.get("/config")
async def get_login_config():
    """获取登录配置"""
    config = _read_login_config()
    return {"login_enabled": config.get("login_enabled", False)}


@router.put("/config")
async def update_login_config(req: LoginConfigRequest):
    """更新登录配置"""
    config = _read_login_config()
    config["login_enabled"] = req.login_enabled
    _write_login_config(config)
    return {"success": True, "login_enabled": req.login_enabled}


@router.post("/setup", response_model=AuthResponse)
async def setup_admin(req: SetupRequest, db: AsyncSession = Depends(get_db)):
    """首次设置管理员账户（仅在无账户时可用）"""
    result = await db.execute(select(AdminUser).limit(1))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="管理员账户已存在，请直接登录")

    if not req.username or len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if not req.password or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")

    user = AdminUser(
        username=req.username,
        role="admin",
        api_key=AdminUser.generate_api_key(),
    )
    user.set_password(req.password)
    db.add(user)
    await db.flush()

    session = AdminSession.new(user.id)
    db.add(session)
    await db.commit()

    return AuthResponse(
        success=True,
        message="账户创建成功",
        token=session.token,
        username=user.username,
        role=user.role,
        api_key=user.api_key,
    )


@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """普通用户注册（需要登录验证开启）"""
    config = _read_login_config()
    if not config.get("login_enabled", False):
        raise HTTPException(status_code=403, detail="登录验证未开启，无法注册")

    if not req.username or len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if not req.password or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")

    # 检查用户名是否已存在
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == req.username)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = AdminUser(
        username=req.username,
        role="user",
        api_key=AdminUser.generate_api_key(),
    )
    user.set_password(req.password)
    db.add(user)
    await db.flush()

    session = AdminSession.new(user.id)
    db.add(session)
    await db.commit()

    return AuthResponse(
        success=True,
        message="注册成功",
        token=session.token,
        username=user.username,
        role=user.role,
        api_key=user.api_key,
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == req.username)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.check_password(req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 为已有 admin 用户补充 api_key（兼容旧数据）
    if not user.api_key:
        user.api_key = AdminUser.generate_api_key()

    session = AdminSession.new(user.id)
    db.add(session)
    await db.commit()

    return AuthResponse(
        success=True,
        message="登录成功",
        token=session.token,
        username=user.username,
        role=user.role or "admin",
        api_key=user.api_key,
    )


@router.post("/change-password", response_model=AuthResponse)
async def change_password(
    req: ChangePasswordRequest,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """修改密码"""
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")

    user = await _get_user_from_token(authorization, db)

    if not user.check_password(req.old_password):
        raise HTTPException(status_code=400, detail="旧密码错误")

    if not req.new_password or len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 个字符")

    user.set_password(req.new_password)
    await db.commit()

    return AuthResponse(
        success=True,
        message="密码修改成功",
    )


@router.post("/logout")
async def logout(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """登出：删除当前 session"""
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        result = await db.execute(
            select(AdminSession).where(AdminSession.token == token)
        )
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()

    return {"success": True, "message": "已登出"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """获取当前登录用户信息"""
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = await _get_user_from_token(authorization, db)
    return _user_to_response(user)


# --------------- 用户管理端点（admin） ---------------

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    auth_info: dict = Depends(get_current_user_info),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表：管理员看全部，普通用户只看自己"""
    if auth_info.get("is_admin"):
        result = await db.execute(select(AdminUser).order_by(AdminUser.id))
    else:
        user_id = auth_info.get("user_id")
        result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    users = result.scalars().all()
    return [_user_to_response(u) for u in users]


@router.post("/users", response_model=UserResponse)
async def create_user(
    req: UserCreateRequest,
    _admin: AdminUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建新用户（仅管理员）"""
    if not req.username or len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if not req.password or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")

    # 检查用户名是否已存在
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == req.username)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")

    supported_models_json = None
    if req.supported_models is not None:
        supported_models_json = json.dumps(req.supported_models, ensure_ascii=False)

    user = AdminUser(
        username=req.username,
        role="user",
        api_key=AdminUser.generate_api_key(),
        supported_models=supported_models_json,
        show_image_square=int(req.show_image_square),
        supported_image_models=json.dumps(req.supported_image_models, ensure_ascii=False) if req.supported_image_models else None,
        daily_token_limit=req.daily_token_limit,
        weekly_token_limit=req.weekly_token_limit,
        monthly_token_limit=req.monthly_token_limit,
        quota_exceeded_mode=req.quota_exceeded_mode or "normal",
        quota_exceeded_message=req.quota_exceeded_message,
        model_mapping=json.dumps(req.model_mapping, ensure_ascii=False) if req.model_mapping else None,
        show_quota_to_user=int(req.show_quota_to_user),
    )
    user.set_password(req.password)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return _user_to_response(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    req: UserUpdateRequest,
    _admin: AdminUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """编辑用户信息（仅管理员）"""
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.username is not None:
        if len(req.username) < 2:
            raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
        # 检查新用户名是否与其他用户冲突
        existing = await db.execute(
            select(AdminUser).where(AdminUser.username == req.username, AdminUser.id != user_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=400, detail="用户名已存在")
        user.username = req.username

    if req.password is not None:
        if len(req.password) < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 个字符")
        user.set_password(req.password)

    if req.role is not None:
        if req.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")
        # 降级管理员时，检查是否是最后一个
        if user.is_admin and req.role != "admin":
            admin_count_result = await db.execute(
                select(AdminUser).where(AdminUser.role == "admin")
            )
            if len(admin_count_result.scalars().all()) <= 1:
                raise HTTPException(status_code=400, detail="不能降级最后一个管理员")
        user.role = req.role

    if req.supported_models is not None:
        user.supported_models = json.dumps(req.supported_models, ensure_ascii=False)

    if req.show_image_square is not None:
        user.show_image_square = int(req.show_image_square)

    if req.supported_image_models is not None:
        user.supported_image_models = json.dumps(req.supported_image_models, ensure_ascii=False) if req.supported_image_models else None

    # 限额字段：有值则更新，clear_xxx=True 则清空
    if req.clear_daily_limit:
        user.daily_token_limit = None
    elif req.daily_token_limit is not None:
        user.daily_token_limit = req.daily_token_limit

    if req.clear_weekly_limit:
        user.weekly_token_limit = None
    elif req.weekly_token_limit is not None:
        user.weekly_token_limit = req.weekly_token_limit

    if req.clear_monthly_limit:
        user.monthly_token_limit = None
    elif req.monthly_token_limit is not None:
        user.monthly_token_limit = req.monthly_token_limit

    if req.quota_exceeded_mode is not None:
        user.quota_exceeded_mode = req.quota_exceeded_mode
    if req.quota_exceeded_message is not None:
        user.quota_exceeded_message = req.quota_exceeded_message or None
    if req.model_mapping is not None:
        user.model_mapping = json.dumps(req.model_mapping, ensure_ascii=False) if req.model_mapping else None
    if req.show_quota_to_user is not None:
        user.show_quota_to_user = int(req.show_quota_to_user)

    await db.commit()
    await db.refresh(user)
    return _user_to_response(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    _admin: AdminUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除用户（仅管理员）"""
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.is_admin:
        # 检查是否是最后一个管理员
        admin_count_result = await db.execute(
            select(AdminUser).where(AdminUser.role == "admin")
        )
        admin_count = len(admin_count_result.scalars().all())
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个管理员")

    # 清理关联的 session
    sessions_result = await db.execute(
        select(AdminSession).where(AdminSession.user_id == user_id)
    )
    for s in sessions_result.scalars().all():
        await db.delete(s)

    await db.delete(user)
    await db.commit()
    return {"success": True, "message": f"用户 {user.username} 已删除"}


@router.post("/users/{user_id}/regenerate-key", response_model=RegenerateKeyResponse)
async def regenerate_user_key(
    user_id: int,
    _admin: AdminUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """重新生成指定用户的 API Key（仅管理员）"""
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.api_key = AdminUser.generate_api_key()
    await db.commit()
    return RegenerateKeyResponse(success=True, api_key=user.api_key)


@router.post("/my/regenerate-key", response_model=RegenerateKeyResponse)
async def regenerate_my_key(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """重新生成当前用户的 API Key"""
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    user = await _get_user_from_token(authorization, db)
    user.api_key = AdminUser.generate_api_key()
    await db.commit()
    return RegenerateKeyResponse(success=True, api_key=user.api_key)
