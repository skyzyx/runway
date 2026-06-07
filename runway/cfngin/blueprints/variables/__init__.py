"""Import modules.

This package exists to separate the variable type system from the core
blueprint logic, keeping the type markers (CFNType, TroposphereType) and
variable resolution in a dedicated namespace so blueprints can import them
without circular dependencies.
"""
