import logging

from pydantic import BaseModel, ConfigDict, Field
from TEMP_NAME.misc.logger import get_logger


class CustomModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )
    logger: logging.Logger = Field(default=get_logger())
