import bcrypt


def get_password_hash(password: str) -> str:
    """Generate a bcrypt hash of a plain text password.
    
    Args:
        password: The plain text password.
        
    Returns:
        The hashed password string (UTF-8 encoded).
    """
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against its bcrypt hash.
    
    Args:
        plain_password: The password to check.
        hashed_password: The bcrypt hashed password to verify against.
        
    Returns:
        True if the password matches, False otherwise.
    """
    password_bytes = plain_password.encode("utf-8")
    try:
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        # Catch errors such as invalid salt/format during verification
        return False
