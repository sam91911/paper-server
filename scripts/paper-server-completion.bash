# Load with: source ./scripts/paper-server-completion.bash

_paper_server_complete() {
    local current=${COMP_WORDS[COMP_CWORD]} previous="" two_back="" prefix="" match
    if (( COMP_CWORD > 0 )); then previous=${COMP_WORDS[COMP_CWORD-1]}; fi
    if (( COMP_CWORD > 1 )); then two_back=${COMP_WORDS[COMP_CWORD-2]}; fi
    local options='-h --help --database --port --public-url --invite-only --storage-quota-mib --interactive --import-csv
        --invite-human --create-account --set-account-role --revoke-human --set-tool-approver --set-ai-operator --register-tool'
    COMPREPLY=()

    case $current in
        --database=*|--import-csv=*) prefix=${current%%=*}=; current=${current#*=} ;;
    esac
    if [[ -n $prefix || $previous == --database || $previous == --import-csv ||
          ( $previous == = && ( $two_back == --database || $two_back == --import-csv ) ) ||
          $two_back == --register-tool || ( $COMP_CWORD == 1 && $current != -* ) ]]; then
        while IFS= read -r match; do
            COMPREPLY+=("$prefix$match")
        done < <(compgen -f -- "$current")
        compopt -o filenames 2>/dev/null || true
    elif [[ $two_back == --set-account-role || $two_back == --create-account ]]; then
        while IFS= read -r match; do
            COMPREPLY+=("$match")
        done < <(compgen -W 'user member local cloud' -- "$current")
    elif [[ ! $previous =~ ^--(port|public-url|storage-quota-mib|invite-human|set-account-role|create-account|revoke-human|set-tool-approver|set-ai-operator|register-tool)$ &&
            $two_back != --set-ai-operator ]]; then
        while IFS= read -r match; do
            COMPREPLY+=("$match")
        done < <(compgen -W "$options" -- "$current")
    fi
}

complete -F _paper_server_complete run_paper_server.sh
