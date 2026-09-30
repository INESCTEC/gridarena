from setuptools import find_packages, setup

setup(
    name="gridarena",
    version="0.1",
    description=(
        "Digital environment to interact with Low Voltage Grids, supporting grid "
        "management, measurement and historical data handling, power flow simulation, "
        "and benchmark-based validation of algorithms for phase mapping, topology "
        "discovery, state estimation, and voltage control."
    ),
    author="David Lima, Gonçalo Cunha, Gil Sampaio",
    author_email="david.lima@inesctec.pt",
    url="https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena",
    license="EUPL-1.2",
    python_requires=">=3.11",
    classifiers=[
        "License :: OSI Approved :: European Union Public Licence 1.2 (EUPL 1.2)",
        "Programming Language :: Python :: 3.11",
    ],
    packages=find_packages(),
    package_data={"gridarena": ["llm/docs/*.md"]},
)
