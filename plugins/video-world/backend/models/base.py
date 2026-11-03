"""
数据库 Base 类定义
单独文件避免循环导入
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
