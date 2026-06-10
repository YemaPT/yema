#!/usr/bin/env sh
set -eu

PACKAGE_NAME="yema"
MIN_PYTHON="3.9"

info() {
    printf '%s\n' "$*"
}

error() {
    printf 'error: %s\n' "$*" >&2
}

detect_shell_rc() {
    shell_name="$(basename "${SHELL:-}")"
    case "$shell_name" in
        zsh)
            printf '%s\n' "$HOME/.zshrc"
            ;;
        bash)
            if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
                printf '%s\n' "$HOME/.bash_profile"
            else
                printf '%s\n' "$HOME/.bashrc"
            fi
            ;;
        *)
            printf '%s\n' "$HOME/.profile"
            ;;
    esac
}

ensure_path_entry() {
    path_dir="$1"
    rc_file="$(detect_shell_rc)"
    path_line="export PATH=\"$path_dir:\$PATH\""

    mkdir -p "$(dirname "$rc_file")"
    touch "$rc_file"

    if grep -F "$path_dir" "$rc_file" >/dev/null 2>&1; then
        info "PATH entry already exists in $rc_file"
        return
    fi

    {
        printf '\n'
        printf '# Added by yema installer\n'
        printf '%s\n' "$path_line"
    } >> "$rc_file"
    info "Added command directory to PATH in $rc_file"
}

find_python() {
    if [ "${PYTHON:-}" ]; then
        command -v "$PYTHON" >/dev/null 2>&1 || {
            error "PYTHON is set to '$PYTHON', but it was not found"
            exit 1
        }
        printf '%s\n' "$PYTHON"
        return
    fi

    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return
        fi
    done

    error "Python ${MIN_PYTHON}+ is required, but python3 was not found"
    exit 1
}

python_bin="$(find_python)"

"$python_bin" - <<'PY'
import sys

minimum = (3, 9)
if sys.version_info < minimum:
    current = ".".join(str(part) for part in sys.version_info[:3])
    required = ".".join(str(part) for part in minimum)
    raise SystemExit(f"Python {required}+ is required, current version is {current}")
PY

if ! "$python_bin" -m pip --version >/dev/null 2>&1; then
    info "pip not found for $python_bin; trying ensurepip..."
    "$python_bin" -m ensurepip --upgrade
fi

install_spec="${YEMA_INSTALL_SPEC:-}"
if [ -z "$install_spec" ]; then
    if [ -f "pyproject.toml" ] && grep -q 'name = "yema"' "pyproject.toml"; then
        install_spec="."
    else
        install_spec="$PACKAGE_NAME"
    fi
fi

info "Installing $install_spec with $python_bin..."
"$python_bin" -m pip install --upgrade --user "$install_spec"

script_dir="$("$python_bin" -m site --user-base)/bin"
script_path="$script_dir/$PACKAGE_NAME"

if [ ! -x "$script_path" ]; then
    error "installed package, but command was not found at $script_path"
    info "Try checking the installation with:"
    info "  $python_bin -m pip show -f $PACKAGE_NAME"
    exit 1
fi

info ""
info "Installed command:"
info "  $script_path"

case ":$PATH:" in
    *":$script_dir:"*)
        info ""
        info "The command directory is already in PATH. You can run:"
        info "  $PACKAGE_NAME --help"
        ;;
    *)
        info ""
        info "The command directory is not in PATH. Updating your shell profile..."
        ensure_path_entry "$script_dir"
        export PATH="$script_dir:$PATH"
        info "PATH updated for this installer session. Restart your shell or source the profile to use '$PACKAGE_NAME' in new sessions."
        ;;
esac

info ""
info "Verifying installation..."
"$script_path" --help >/dev/null
info "OK"
