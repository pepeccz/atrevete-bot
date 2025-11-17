"""
Django settings for Atrévete Admin

This Django Admin panel uses the existing PostgreSQL database managed by Alembic.
NO Django migrations should be run - all database management is done via Alembic.
"""

import os
import sys
from pathlib import Path

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

# Add project root to Python path to import shared modules
sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import get_settings

settings = get_settings()

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv(
    'DJANGO_SECRET_KEY',
    'django-insecure-development-key-change-in-production'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party apps
    'django_extensions',
    'import_export',
    # Project apps
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files efficiently
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'atrevete_admin.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'atrevete_admin.wsgi.application'

# Database
# Convert asyncpg URL to psycopg URL for Django
database_url = settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')

# Parse database URL manually for Django DATABASES config
# Format: postgresql://user:password@host:port/database
if database_url.startswith('postgresql://'):
    import re
    match = re.match(
        r'postgresql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<name>.+)',
        database_url
    )
    if match:
        db_config = match.groupdict()
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': db_config['name'],
                'USER': db_config['user'],
                'PASSWORD': db_config['password'],
                'HOST': db_config['host'],
                'PORT': db_config['port'],
            }
        }
    else:
        # Fallback to env vars if parsing fails
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': settings.POSTGRES_DB,
                'USER': settings.POSTGRES_USER,
                'PASSWORD': settings.POSTGRES_PASSWORD,
                'HOST': os.getenv('POSTGRES_HOST', 'postgres'),
                'PORT': os.getenv('POSTGRES_PORT', '5432'),
            }
        }
else:
    # Fallback configuration
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': settings.POSTGRES_DB,
            'USER': settings.POSTGRES_USER,
            'PASSWORD': settings.POSTGRES_PASSWORD,
            'HOST': os.getenv('POSTGRES_HOST', 'postgres'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }
    }

# Database Router - CRITICAL: Prevents Django migrations for core app
DATABASE_ROUTERS = ['atrevete_admin.router.UnmanagedRouter']

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'es-es'  # Spanish (Spain)

TIME_ZONE = settings.TIMEZONE  # Europe/Madrid

USE_I18N = True

USE_TZ = True  # Use timezone-aware datetimes

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# WhiteNoise configuration for serving static files with Gunicorn
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django Admin customization
ADMIN_SITE_HEADER = 'Atrévete Admin'
ADMIN_SITE_TITLE = 'Atrévete Admin'
ADMIN_INDEX_TITLE = 'Panel de Administración'
