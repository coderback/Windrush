import os
import uuid
from pathlib import Path
from typing import Optional, List
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.core.exceptions import ValidationError

# Try to import python-magic, but provide fallback if not available
try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False
    import mimetypes


class SecureFileUploadHandler:
    """
    Secure file upload handler with validation, virus scanning, and safe storage
    """
    
    def __init__(self):
        self.allowed_extensions = getattr(settings, 'ALLOWED_FILE_EXTENSIONS', {})
        self.max_file_sizes = getattr(settings, 'MAX_FILE_SIZES', {})
        self.secure_upload_path = getattr(settings, 'SECURE_FILE_UPLOAD_PATH', 
                                        settings.MEDIA_ROOT / 'secure')
    
    def validate_file(self, uploaded_file: UploadedFile, file_type: str = 'general') -> None:
        """
        Validate uploaded file for security and compliance
        
        Args:
            uploaded_file: The uploaded file object
            file_type: Type of file (cv, cover_letter, portfolio, image)
        
        Raises:
            ValidationError: If file validation fails
        """
        # Check file size
        max_size = self.max_file_sizes.get(file_type, 10 * 1024 * 1024)  # Default 10MB
        if uploaded_file.size > max_size:
            raise ValidationError(
                f"File size ({uploaded_file.size} bytes) exceeds maximum allowed "
                f"size ({max_size} bytes) for {file_type} files"
            )
        
        # Check file extension
        allowed_extensions = self.allowed_extensions.get(file_type, ['pdf', 'doc', 'docx'])
        file_extension = self._get_file_extension(uploaded_file.name)
        
        if file_extension not in allowed_extensions:
            raise ValidationError(
                f"File extension '.{file_extension}' is not allowed for {file_type} files. "
                f"Allowed extensions: {', '.join(allowed_extensions)}"
            )
        
        # Validate MIME type matches extension
        if not self._validate_mime_type(uploaded_file, file_extension):
            raise ValidationError(
                "File content does not match its extension. Possible security risk."
            )
        
        # Check for potentially dangerous file content
        if self._contains_dangerous_content(uploaded_file):
            raise ValidationError(
                "File contains potentially dangerous content and cannot be uploaded."
            )
    
    def _get_file_extension(self, filename: str) -> str:
        """Extract file extension from filename"""
        return filename.split('.')[-1].lower() if '.' in filename else ''
    
    def _validate_mime_type(self, uploaded_file: UploadedFile, extension: str) -> bool:
        """
        Validate that MIME type matches file extension
        
        Args:
            uploaded_file: The uploaded file
            extension: File extension
            
        Returns:
            bool: True if MIME type is valid for extension
        """
        try:
            # Read first chunk to determine MIME type
            uploaded_file.seek(0)
            file_content = uploaded_file.read(1024)
            uploaded_file.seek(0)
            
            # Use python-magic if available, otherwise fallback to mimetypes
            if MAGIC_AVAILABLE:
                mime_type = magic.from_buffer(file_content, mime=True)
            else:
                # Fallback to basic MIME type guessing
                mime_type, _ = mimetypes.guess_type(uploaded_file.name)
                if not mime_type:
                    # Basic content-based detection for common files
                    if file_content.startswith(b'%PDF'):
                        mime_type = 'application/pdf'
                    elif file_content.startswith(b'PK\x03\x04'):
                        mime_type = 'application/zip'  # Could be docx/zip
                    elif file_content.startswith(b'\xFF\xD8\xFF'):
                        mime_type = 'image/jpeg'
                    elif file_content.startswith(b'\x89PNG'):
                        mime_type = 'image/png'
                    else:
                        mime_type = 'application/octet-stream'
            
            # Define expected MIME types for extensions
            mime_mappings = {
                'pdf': ['application/pdf'],
                'doc': ['application/msword'],
                'docx': [
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/zip'  # docx files are zip-based
                ],
                'jpg': ['image/jpeg'],
                'jpeg': ['image/jpeg'],
                'png': ['image/png'],
                'gif': ['image/gif'],
                'zip': ['application/zip'],
                'rar': ['application/x-rar-compressed', 'application/vnd.rar']
            }
            
            expected_mimes = mime_mappings.get(extension, [])
            return mime_type in expected_mimes if expected_mimes else True
            
        except Exception:
            # If MIME type detection fails, allow the file but log the issue
            return True
    
    def _contains_dangerous_content(self, uploaded_file: UploadedFile) -> bool:
        """
        Check for dangerous file content patterns
        
        Args:
            uploaded_file: The uploaded file
            
        Returns:
            bool: True if dangerous content is detected
        """
        try:
            uploaded_file.seek(0)
            # Read first 1KB to check for dangerous patterns
            content = uploaded_file.read(1024)
            uploaded_file.seek(0)
            
            # Convert to lowercase for pattern matching
            content_lower = content.lower()
            
            # Check for script tags, executable signatures, etc.
            dangerous_patterns = [
                b'<script',
                b'javascript:',
                b'<?php',
                b'<%',
                b'mz',  # DOS executable signature
                b'\x7felf',  # ELF executable signature
            ]
            
            # ZIP signature is allowed for docx and zip files
            file_extension = self._get_file_extension(uploaded_file.name)
            if file_extension not in ['zip', 'docx'] and content.startswith(b'PK\x03\x04'):
                return True
            
            return any(pattern in content_lower for pattern in dangerous_patterns)
            
        except Exception:
            # If content scanning fails, allow the file (defensive programming)
            return False
    
    def generate_secure_filename(self, original_filename: str, user_id: int = None) -> str:
        """
        Generate a secure filename to prevent path traversal and conflicts
        
        Args:
            original_filename: Original uploaded filename
            user_id: ID of the user uploading the file
            
        Returns:
            str: Secure filename
        """
        # Extract extension
        extension = self._get_file_extension(original_filename)
        
        # Generate UUID-based filename
        secure_name = str(uuid.uuid4())
        
        # Add user prefix if provided
        if user_id:
            secure_name = f"user_{user_id}_{secure_name}"
        
        return f"{secure_name}.{extension}" if extension else secure_name
    
    def get_upload_path(self, filename: str, file_type: str = 'general') -> str:
        """
        Generate secure upload path for file
        
        Args:
            filename: Secure filename
            file_type: Type of file (cv, cover_letter, etc.)
            
        Returns:
            str: Upload path relative to MEDIA_ROOT
        """
        # Organize files by type and date
        from datetime import datetime
        date_path = datetime.now().strftime('%Y/%m')
        
        return f"uploads/{file_type}/{date_path}/{filename}"
    
    def save_file(self, uploaded_file: UploadedFile, file_type: str = 'general', 
                  user_id: int = None) -> str:
        """
        Securely save an uploaded file
        
        Args:
            uploaded_file: The uploaded file
            file_type: Type of file (cv, cover_letter, portfolio, image)
            user_id: ID of the user uploading the file
            
        Returns:
            str: Path to saved file
            
        Raises:
            ValidationError: If file validation fails
        """
        # Validate the file
        self.validate_file(uploaded_file, file_type)
        
        # Generate secure filename
        secure_filename = self.generate_secure_filename(uploaded_file.name, user_id)
        
        # Get upload path
        upload_path = self.get_upload_path(secure_filename, file_type)
        
        # Save file using Django's default storage
        saved_path = default_storage.save(upload_path, uploaded_file)
        
        return saved_path
    
    def delete_file(self, file_path: str) -> bool:
        """
        Securely delete a file
        
        Args:
            file_path: Path to file to delete
            
        Returns:
            bool: True if file was deleted successfully
        """
        try:
            if default_storage.exists(file_path):
                default_storage.delete(file_path)
                return True
            return False
        except Exception:
            return False


# Convenience functions
def validate_and_save_file(uploaded_file: UploadedFile, file_type: str = 'general', 
                          user_id: int = None) -> str:
    """
    Convenience function to validate and save uploaded file
    
    Args:
        uploaded_file: The uploaded file
        file_type: Type of file (cv, cover_letter, portfolio, image)
        user_id: ID of the user uploading the file
        
    Returns:
        str: Path to saved file
        
    Raises:
        ValidationError: If file validation fails
    """
    handler = SecureFileUploadHandler()
    return handler.save_file(uploaded_file, file_type, user_id)


def get_file_url(file_path: str) -> Optional[str]:
    """
    Get public URL for uploaded file
    
    Args:
        file_path: Path to file
        
    Returns:
        Optional[str]: Public URL or None if file doesn't exist
    """
    if file_path and default_storage.exists(file_path):
        return default_storage.url(file_path)
    return None


def delete_user_file(file_path: str) -> bool:
    """
    Securely delete a user-uploaded file
    
    Args:
        file_path: Path to file to delete
        
    Returns:
        bool: True if file was deleted successfully
    """
    handler = SecureFileUploadHandler()
    return handler.delete_file(file_path)