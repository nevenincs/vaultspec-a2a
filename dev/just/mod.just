set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod build
mod code
mod deps
mod doctor
mod hooks
mod product
mod rag
mod service
mod stack
mod test
mod vault

# Show every developer module and recipe.
help:
    @just --list dev --list-submodules
