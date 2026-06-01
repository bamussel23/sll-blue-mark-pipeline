from setuptools import setup, find_packages

setup(
    name="stresscon",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "office365-rest-python-client>=2.5.0",
        "pandas>=2.0.0",
        "python-dotenv>=1.0.0",
        "fuzzywuzzy>=0.18.0",
        "python-Levenshtein>=0.21.0",
    ],
    python_requires=">=3.9",
    description="Stresscon Operations Suite - Maintenance Analytics",
)
