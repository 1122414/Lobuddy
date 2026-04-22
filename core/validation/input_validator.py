"""Input validation layer for task and model inputs."""


class ValidationError(Exception):
    """Raised when input validation fails."""

    pass


class InputValidator:
    """Validates user inputs before they reach business logic."""

    MAX_INPUT_TEXT_LENGTH: int = 4000
    MAX_SESSION_ID_LENGTH: int = 128
    MAX_IMAGE_PATH_LENGTH: int = 512

    @classmethod
    def validate_submit_task(
        cls,
        input_text: str,
        session_id: str,
        image_path: str = "",
    ) -> None:
        """Validate arguments for TaskManager.submit_task().

        Raises:
            ValidationError: If any field fails validation.
        """
        stripped = input_text.strip()
        if not stripped:
            raise ValidationError("input_text cannot be empty")

        if len(stripped) > cls.MAX_INPUT_TEXT_LENGTH:
            raise ValidationError(
                f"input_text exceeds maximum length of {cls.MAX_INPUT_TEXT_LENGTH}"
            )

        if not session_id.strip():
            raise ValidationError("session_id cannot be empty")

        if len(session_id) > cls.MAX_SESSION_ID_LENGTH:
            raise ValidationError(
                f"session_id exceeds maximum length of {cls.MAX_SESSION_ID_LENGTH}"
            )

        if len(image_path) > cls.MAX_IMAGE_PATH_LENGTH:
            raise ValidationError(
                f"image_path exceeds maximum length of {cls.MAX_IMAGE_PATH_LENGTH}"
            )
