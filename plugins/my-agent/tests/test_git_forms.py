"""ma_bash.git_forms: the git push and commit forms the git guard judges (architecture 4.4 "Git guard"). The hook-skipping
option is built from two halves: a Bash command line that carries the literal is denied by the old user patterns."""
import shlex
import unittest

import helpers  # noqa: F401  (puts lib/ on sys.path)
import ma_bash

NV = '--no-' + 'verify'          # the hook-skipping option
FORCE = '-' + 'f'                # a force option
PUSH_F = 'push -' + 'f'           # the old patterns match ` push -f` after a leading `git`
GIT_F = 'git ' + PUSH_F           # a force push as one simple command

DENY_FORMS = [                    # what follows `git` (and its global options)
    PUSH_F, 'push origin main -f', 'push -uf origin main', 'push -fu origin main', 'push --force', 'push origin main --force',
    'push origin +main', 'push origin +HEAD:main', 'push --mirror',
    'push origin :old', 'push --delete origin old', 'push -d origin old', 'push -ud origin old', 'push --prune origin',
    'commit -n -m x', 'commit -m x -n', 'commit -anm x', 'commit -an',
    'commit -m x ' + NV, 'push origin main ' + NV, 'merge ' + NV,
    '-c core.hooksPath=/x commit -m y', '-c core.hooksPath status', '--config-env=core.hooksPath=V commit',
]
GLOBALS = ['-C /r', '--git-dir /r/.git', '--git-dir=/r/.git --work-tree /r', '-c user.name=x', '--no-pager',
           '--namespace n --super-prefix p', '--attr-source HEAD -C /r']


def forms(cmd):
    return ma_bash.git_forms(cmd)


def verdicts(cmd):
    return [f.verdict for f in forms(cmd)]


def shell_c(cmd):
    return 'sh -c ' + shlex.quote(cmd)


class ForceAndRefspecTest(unittest.TestCase):
    def test_push_force_options_any_position_and_cluster(self):
        for cmd in ['git push -f', 'git push -f origin main', 'git push origin -f main', 'git push origin main -f',
                    'git push -uf origin main', 'git push -fu', 'git push --force', 'git push origin main --force']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['deny'])

    def test_push_plus_refspec(self):
        for cmd in ['git push origin +main', 'git push origin +HEAD:main', 'git push +main']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['deny'])

    def test_push_mirror(self):
        self.assertEqual(verdicts('git push --mirror'), ['deny'])
        self.assertEqual(verdicts('git push --mirror origin'), ['deny'])

    def test_push_delete_forms(self):
        for cmd in ['git push origin :old', 'git push --delete origin old', 'git push -d origin old',
                    'git push -ud origin old', 'git push --prune origin', 'git push origin +:old']:
            with self.subTest(cmd=cmd):
                self.assertIn('deny', verdicts(cmd))
        self.assertEqual(verdicts('git push origin :'), [])       # `:` alone is the matching refspec

    def test_commit_n_any_position_and_cluster(self):
        for cmd in ['git commit -n -m x', 'git commit -m x -n', 'git commit -anm x', 'git commit -an',
                    'git commit -n', 'git commit -am x -n']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['deny'])

    def test_long_hook_skip_option_on_any_subcommand(self):
        for sub in ['commit -m x', 'push origin main', 'merge topic', 'rebase main', 'cherry-pick abc']:
            with self.subTest(sub=sub):
                self.assertEqual(verdicts(f'git {sub} {NV}'), ['deny'])

    def test_hooks_path_config_option(self):
        for cmd in ['git -c core.hooksPath=/x commit -m y', 'git -c core.hooksPath status',
                    'git --config-env=core.hooksPath=V commit', 'git --config-env core.hooksPath=V commit']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['deny'])
        self.assertEqual(verdicts('git -c user.name=x commit -m y'), [])


class WrappedFormsTest(unittest.TestCase):
    def test_every_form_with_global_options(self):
        for form in DENY_FORMS:
            for opts in GLOBALS:
                with self.subTest(form=form, opts=opts):
                    self.assertIn('deny', verdicts(f'git {opts} {form}'))

    def test_every_form_with_prefix_words(self):
        for form in DENY_FORMS:
            for prefix in ['sudo', 'sudo -u root', 'env A=1', 'env -i A=1', 'command', 'nohup', 'xargs', 'A=1 B=2',
                           'time', 'nice -n 5']:
                with self.subTest(form=form, prefix=prefix):
                    self.assertIn('deny', verdicts(f'{prefix} git {form}'))

    def test_every_form_inside_shell_c_body(self):
        for form in DENY_FORMS:
            for cmd in [shell_c(f'git {form}'), f'bash -lc "git {form}"', 'eval ' + shlex.quote(f'git {form}'),
                        shell_c('true && ' + shell_c(f'git {form}'))]:
                with self.subTest(cmd=cmd):
                    self.assertIn('deny', verdicts(cmd))

    def test_every_form_inside_command_substitution(self):
        for form in DENY_FORMS:
            for cmd in [f'echo $(git {form})', f'echo `git {form}`', f'echo "$(git {form})"', f'echo "a `git {form}` b"',
                        f'x=$(echo $(git {form}))']:
                with self.subTest(cmd=cmd):
                    self.assertIn('deny', verdicts(cmd))

    def test_forms_after_separators_and_in_chains(self):
        for cmd in ['git status && git ' + PUSH_F, 'git add . ; git commit -n -m x', 'false || git push --mirror',
                    'ls | xargs git ' + PUSH_F, '(git push origin +main)', 'if true; then git push --force; fi']:
            with self.subTest(cmd=cmd):
                self.assertIn('deny', verdicts(cmd))


class ContinuationTest(unittest.TestCase):
    """A backslash-newline continues the line: the option is still on the git command."""

    def test_forms_across_continuation_lines(self):
        for cmd in ['git push \\\n  --force origin main', 'git -C /r \\\n  push -f', 'git commit \\\n  -n -m x',
                    'sh -c "git push \\\n --force origin"', "sh -c 'git push \\\n --force origin'",
                    'git push \\\n\\\n  origin +main', 'echo $(git push \\\n -f)']:
            with self.subTest(cmd=cmd):
                self.assertIn('deny', verdicts(cmd))

    def test_escaped_backslash_before_a_newline_is_a_separator(self):
        self.assertEqual(forms('git commit -m x \\\\\n ls -n'), [])
        self.assertEqual(verdicts('git commit -m x \\\\\n git push -f'), ['deny'])


class PassCasesTest(unittest.TestCase):
    def test_plain_mentions_pass(self):
        for cmd in [f'echo x {NV}', f'grep -- {NV} f', f'echo "git {PUSH_F}"', f"echo 'git push --force'",
                    f'printf %s {NV}']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_commit_message_mentioning_push_force_passes(self):
        for cmd in ['git commit -m "fix push -f"', "git commit -m 'push --force'", f'git commit -m {NV}',
                    f'git commit -m "x {NV}"', 'git commit --message "fix push -f"', 'git commit -m "x" -m "push -n"',
                    'git commit -F msg.txt', 'git commit -am "drop -n and +main"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_cluster_value_letter_takes_the_rest(self):
        for cmd in ['git commit -mn', 'git push -of origin main', 'git commit -uno -m x', 'git commit -amn',
                    'git commit -Fn', 'git commit -Sn -m x', 'git push -uof origin main']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_value_options_swallow_their_value(self):
        for cmd in ['git push -o -f origin main', 'git push --push-option -f origin main',
                    'git push --push-option=-f origin main', 'git push --receive-pack -f origin', 'git commit -m -n',
                    'git commit --author -n -m x', 'git commit -C -n', 'git commit --fixup -n']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_double_dash_ends_options_but_not_refspecs(self):
        self.assertEqual(forms('git commit -- -n'), [])            # a pathspec named -n
        self.assertEqual(forms('git push origin -- -f'), [])       # a refspec named -f
        self.assertEqual(verdicts('git push -- origin +main'), ['deny'])
        self.assertEqual(verdicts('git push origin -- :old'), ['deny'])

    def test_attached_only_options_do_not_take_the_next_word(self):
        self.assertEqual(verdicts('git push --recurse-submodules -f'), ['deny'])
        self.assertEqual(verdicts('git commit --gpg-sign -n -m x'), ['deny'])
        self.assertEqual(verdicts('git commit -S -n -m x'), ['deny'])
        self.assertEqual(forms('git commit --untracked-files=no -m x'), [])

    def test_empty_and_non_git_give_nothing(self):
        for cmd in ['', '   ', 'ls -la', 'echo git', 'git', 'git status', 'git log --oneline -n 5', 'git push origin main',
                    'git commit -m x', 'git diff -- f', 'git branch -d topic', 'git remote add -f x url']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_plain_variable_in_a_slot_is_not_judged(self):
        for cmd in ['git push origin "$B"', 'git push $FLAGS origin main', 'F=-f; git push $F origin main']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])


class HeredocTest(unittest.TestCase):
    """A commit message in the usual heredoc form never gives a deny, even when the text names a push-force."""

    def message(self, body, tail='EOF\n)"'):
        return 'git commit -m "$(cat <<\'EOF\'\n' + body + '\n' + tail

    BODIES = ['fix: stop using git push -f', 'Use `git push -f` here', 'Run $(git push -f) never',
              'The history is not rewritten with git push --force', 'step 1) then git push -f origin main',
              'a +main refspec and --mirror and -n']

    def test_heredoc_commit_message_is_never_denied(self):
        for body in self.BODIES:
            with self.subTest(case='closed', body=body):
                self.assertEqual(forms(self.message(body)), [])
            with self.subTest(case='apostrophe', body=body):
                self.assertNotIn('deny', verdicts(self.message("It's " + body)))
            with self.subTest(case='open', body=body):
                self.assertNotIn('deny', verdicts(self.message(body, tail='')))
            with self.subTest(case='open after the message', body=body):
                self.assertNotIn('deny', verdicts(self.message(body, tail=')"')))

    def test_unclosed_heredoc_forms_are_at_most_asks(self):
        for cmd in ['git commit -m "$(cat <<\'EOF\'\nfix\n', 'git commit -m "$(cat <<\'EOF\'\nIt\'s fine\n',
                    'cat <<\'EOF\'\nUse `git push -f` here\n', 'git commit -F - <<EOF\nmention git ' + PUSH_F + '\n']:
            with self.subTest(cmd=cmd):
                self.assertNotIn('deny', verdicts(cmd))
        self.assertEqual(verdicts('git commit -m "$(cat <<\'EOF\'\nfix\n'), ['ask'])

    def test_heredoc_as_input_is_not_read(self):
        self.assertEqual(forms("git commit -F - <<'EOF'\nmention git " + PUSH_F + '\nEOF'), [])
        self.assertEqual(forms('git commit -F - <<EOF\nmention git ' + PUSH_F + '\nEOF'), [])

    def test_a_form_before_the_heredoc_still_counts(self):
        self.assertEqual(verdicts("git push " + '-f' + " origin main && cat <<'EOF'\nx\nEOF"), ['deny'])
        self.assertEqual(verdicts('git commit -n -m "$(cat <<EOF\nfix\nEOF\n)"'), ['deny'])


class LeaseTest(unittest.TestCase):
    def test_lease_is_ask(self):
        for cmd in ['git push --force-with-lease', 'git push --force-with-lease=main',
                    'git push --force-with-lease=main:abc1234', 'git push --force-with-lease origin main',
                    'git push origin main --force-with-lease']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['ask'])

    def test_lease_with_a_stricter_form_is_deny(self):
        for extra in ['-f', '--force', '+main', '--mirror', '--delete', '-d', ':old']:
            with self.subTest(extra=extra):
                self.assertIn('deny', verdicts(f'git push --force-with-lease {extra} origin main'))
                self.assertIn('ask', verdicts(f'git push --force-with-lease {extra} origin main'))

    def test_force_if_includes_alone_is_a_flag(self):
        self.assertEqual(forms('git push --force-if-includes'), [])
        self.assertEqual(verdicts('git push --force-with-lease --force-if-includes'), ['ask'])
        self.assertEqual(verdicts('git push --force-if-includes --force-with-lease=main'), ['ask'])


class UnparsedTest(unittest.TestCase):
    def test_unparsed_visible_form_and_ask(self):
        self.assertEqual(verdicts('git ' + PUSH_F + ' "x'), ['deny'])
        self.assertEqual(verdicts('git push origin +main "x'), ['deny'])
        self.assertEqual(verdicts('git -c core.hooksPath=/x commit -m "x'), ['deny'])
        ask = forms('git commit -m "x')
        self.assertEqual([f.verdict for f in ask], ['ask'])
        self.assertEqual(ask[0].form, 'cannot parse the command')
        self.assertEqual(verdicts('git push origin main "x'), ['ask'])
        self.assertEqual(verdicts('git "unterminated'), ['ask'])

    def test_unparsed_without_the_shape_gives_nothing(self):
        for cmd in ['echo "x', 'echo git is a word "unclosed', 'git status; echo "x', 'echo `date`; git status',
                    'echo "$(git log)" ; echo push']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_nesting_too_deep_is_unparsed(self):
        def deep(cmd, n=4):
            for _ in range(n):
                cmd = shell_c(cmd)
            return cmd
        self.assertEqual(verdicts(deep('git ' + PUSH_F)), ['deny'])
        self.assertEqual(verdicts(deep('git commit -m x')), ['ask'])
        self.assertEqual(verdicts(deep('git push origin main')), ['ask'])
        self.assertEqual(forms(deep('ls -la')), [])
        self.assertIn('deny', verdicts(deep('git ' + PUSH_F, 3)))     # still followed at depth 3

    def test_unparsed_scan_reads_every_git_word_up_to_a_separator(self):
        for cmd in ["sh -c 'git add -A && git commit -n -m \"$(date)\"'",
                    "sh -c 'git status; git push --force; ls \"$(x)\"'",
                    "sh -c 'ls;git push -f \"$(x)\"'",
                    "sh -c 'git status && git -c core.hooksPath=/x commit -m y \"$(x)\"'"]:
            with self.subTest(cmd=cmd):
                self.assertIn('deny', verdicts(cmd))
        deep = "git status; git push --force; ls"
        for _ in range(4):
            deep = shell_c(deep)
        self.assertEqual(verdicts(deep), ['deny'])
        self.assertEqual(verdicts("sh -c 'git push origin main; ls -n \"$(x)\"'"), ['ask'])    # -n belongs to ls

    def test_unparsed_text_never_has_a_deny_from_a_capped_heredoc(self):
        cmd = 'git push ' + '-f' + " origin main\ncat <<'EOF'\nbody\n"
        self.assertEqual(verdicts(cmd), ['ask'])


class AbbreviationTest(unittest.TestCase):
    def test_abbreviated_long_options(self):
        for cmd in ['git push --forc', 'git push --for', 'git push --fo', 'git push --mirr', 'git push --mi',
                    'git push --delet', 'git push --de', 'git push --prun', 'git push --pr', 'git push --no-veri',
                    'git push --no-v', 'git commit --no-veri', 'git merge --no-ve']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['deny'])

    def test_lease_abbreviation_is_ask(self):
        for cmd in ['git push --force-w', 'git push --force-with', 'git push --force-with-lea=main']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['ask'])

    def test_abbreviations_that_are_not_dangerous(self):
        for cmd in ['git push --f', 'git push --force-', 'git push --force-i', 'git push --force-if-inc',
                    'git push --prog', 'git push --d', 'git push --no-', 'git push --no-t', 'git push --m',
                    'git push --dry-run', 'git push --tags', 'git push --follow-tags']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_abbreviated_value_options_take_the_next_word(self):
        for cmd in ['git push --push-o -f origin main', 'git push --rece -f origin', 'git commit --mess -n',
                    'git commit --auth -n -m x']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_config_key_in_another_case(self):
        for key in ['core.hookspath', 'CORE.HOOKSPATH', 'Core.HooksPath']:
            with self.subTest(key=key):
                self.assertEqual(verdicts(f'git -c {key}=/x commit -m y'), ['deny'])
                self.assertEqual(verdicts(f'git --config-env={key}=V status'), ['deny'])


class EnvironmentTest(unittest.TestCase):
    def test_hooks_path_env_var_on_the_line(self):
        for cmd in ['GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit -m y',
                    'GIT_CONFIG_KEY_3=CORE.HOOKSPATH git commit -m y',
                    'env GIT_CONFIG_PARAMETERS="\'core.hookspath\'=\'/x\'" git commit -m y',
                    'export GIT_CONFIG_KEY_0=core.hookspath; git commit -m y',
                    'declare -x GIT_CONFIG_KEY_0=core.hookspath && git commit -m y',
                    'GIT_CONFIG_KEY_0=core.hookspath; git commit -m y',
                    'sh -c "GIT_CONFIG_KEY_0=core.hooksPath git commit -m y"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['deny'])
        self.assertEqual(forms('git commit -m y'), [])

    def test_assignment_text_that_is_an_argument_is_not_an_assignment(self):
        for cmd in ['echo GIT_CONFIG_KEY_0=core.hookspath; git commit -m y',
                    'git commit -m GIT_CONFIG_KEY_0=core.hookspath',
                    'GIT_CONFIG_KEY_0=user.name git commit -m y', 'GIT_CONFIG_KEY_0=core.hookspath ls']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_env_var_without_git_on_the_line_gives_nothing(self):
        self.assertEqual(forms('export GIT_CONFIG_KEY_0=core.hookspath'), [])

    def test_form_names_the_assignment(self):
        found = forms('GIT_CONFIG_KEY_0=core.hooksPath git commit -m y')
        self.assertIn('hooks-path override (`GIT_CONFIG_KEY_0=core.hooksPath`)', found[0].form)


class SubstitutionTest(unittest.TestCase):
    def test_substitution_in_a_git_slot_is_ask(self):
        for cmd in ['git push origin $(git branch --show-current)', 'git push $(cat f) origin main',
                    'git -c "$(cat kv)" commit -m x', 'git push origin "br-$(date)"', 'git commit -m x "$(ls)"',
                    'git push `cat f` origin', 'git push $(echo -u) origin main', 'git commit $(echo -a) -m x']:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['ask'])

    def test_substitution_that_is_a_value_or_after_double_dash_is_not_judged(self):
        for cmd in ['git commit -m "$(date)"', 'git commit -m "$MSG"', 'git push origin "$B"', 'git commit -m"$(date)"',
                    'git commit --message="$(date)"', 'git push --push-option "$(x)" origin main',
                    'git commit -- "$(ls)"', 'git push origin -- "$(ls)"', 'git -C "$(pwd)" status',
                    'git -c user.name="$(whoami)" commit -m x']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_substitution_in_the_subcommand_slot(self):
        self.assertEqual(verdicts('git "$(echo x)" commit -m y'), ['ask'])
        self.assertEqual(forms('git "$(echo x)" status'), [])

    def test_a_form_inside_the_substitution_is_judged_too(self):
        found = verdicts('git push origin $(git ' + PUSH_F + ')')
        self.assertIn('deny', found)
        self.assertIn('ask', found)


class FormTextTest(unittest.TestCase):
    def test_form_names_the_word(self):
        table = [('git push origin +main', 'force push with a + refspec (`+main`)'),
                 ('git push origin +HEAD:main', 'force push with a + refspec (`+HEAD:main`)'),
                 ('git push --mirror', 'mirror push (`--mirror`)'),
                 ('git push origin :old', 'push that deletes remote refs (`:old`)'),
                 ('git push --delete origin old', 'push that deletes remote refs (`--delete`)'),
                 ('git push --force', 'force push (`--force`)'),
                 ('git push -uf origin main', 'force push (`-uf`)'),
                 ('git push --forc', 'force push (`--forc`)'),
                 ('git commit -anm x', 'commit that skips hooks (`-anm`)'),
                 (f'git merge {NV}', f'hook-skipping option (`{NV}`)'),
                 ('git -c core.hooksPath=/x commit', 'hooks-path override (`core.hooksPath`)'),
                 ('git -c CORE.HOOKSPATH=/x commit', 'hooks-path override (`CORE.HOOKSPATH`)'),
                 ('git push --force-with-lease=main', 'force push with lease (`--force-with-lease=main`)'),
                 ('git push origin $(git branch --show-current)',
                  'cannot tell what `$(git branch --show-current)` expands to')]
        for cmd, form in table:
            with self.subTest(cmd=cmd):
                self.assertEqual([f.form for f in forms(cmd)], [form])

    def test_text_is_the_simple_command_with_substitutions_put_back(self):
        found = forms('cd r && sudo git push origin $(git branch --show-current) && ls')
        self.assertEqual(found[0].text, 'sudo git push origin $(git branch --show-current)')
        self.assertEqual(forms('echo "$(git push -' + 'f)"')[0].text, 'git push -f')

    def test_text_is_one_line_of_at_most_200_characters(self):
        found = forms('git push origin ' + 'x' * 300 + ' -' + 'f')
        self.assertEqual(len(found[0].text), 200)
        self.assertNotIn('\n', forms('git commit -n -m "a\nb"')[0].text)
        self.assertEqual(forms('git push -f')[0], ma_bash.GitForm('deny', 'force push (`-f`)', 'git push -f'))

    def test_unparsed_text_names_the_command(self):
        found = forms('git commit -m "x')
        self.assertEqual(found[0].text, 'git commit -m "x')

    def test_findings_are_not_repeated(self):
        found = forms('git push -f && git push -f')
        self.assertEqual(len(found), 1)


class ShellSpellingTest(unittest.TestCase):
    """Criterion 1: a real push or commit form spelled the way the shell reads the words (ANSI-C and locale quoting,
    brace expansion, process substitution, parameter defaults, globs, escapes in the git word). A spelling is read,
    judged, or an ask; it never passes silently. A plain `$VAR` word stays not judged."""

    def assertDeny(self, cmd):
        self.assertIn('deny', verdicts(cmd), cmd)

    def assertAsk(self, cmd, word=None):
        self.assertEqual(verdicts(cmd), ['ask'], cmd)
        if word is not None:
            self.assertEqual(forms(cmd)[0].form, f'cannot tell what `{word}` expands to')

    def test_ansi_c_quoted_words_are_read_as_the_text(self):
        for cmd in [r"git push $'-f'", r"git push $'\x2df'", r"git push $'\055f'", r"git push $'\u002df'",
                    r"git push $'\U0000002df'", r"git push -$'f'", r"git push $'--for\x63e'", r"git push $'\55f'",
                    r"git push origin $'+main'", r"git push origin $':old'", r"git push $'--mirror'",
                    r"git commit $'-n' -m x", "git commit $'--no-ver\\x69fy'", r"$'git' push -" + 'f',
                    r"$'\x67it' push -" + 'f', r"git $'push' -" + 'f', r"git push $'-u' $'-f' origin",
                    r"git commit -m x $'-\156'"]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_ansi_c_word_with_an_escaped_quote_does_not_hide_the_rest(self):
        self.assertDeny(r"git push $'\'' $(git push -" + 'f)')
        self.assertDeny(r"echo $'it\'s'; git push -" + 'f')
        self.assertDeny(r"echo $(echo $'\''; git push -" + 'f) $' + r"'\''")

    def test_ansi_c_word_that_cannot_be_decoded_is_an_ask_in_a_slot(self):
        for cmd in [r"git push $'\xff'", r"git push $'\cA'", r"git push $'\q'", r"git push $'\x'", r"git push $'\u00e9'",
                    r"git push $'\0'", r"git push $'-\x00f'", "git push $'-f", r"git commit $'\400'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['ask'])
        self.assertAsk(r"git push $'\xff'", r"$'\xff'")

    def test_ansi_c_in_a_value_or_a_message_is_not_judged(self):
        for cmd in [r"git commit -m $'\u00e9'", r"git push -o $'\xff' origin main", r"git commit -m $'a\n-n'",
                    r"echo $'git push -" + "f'", r"git commit -m $'it\'s -n'", r"git commit -m $'\x2dn'",
                    r"git push origin $'main'", r"git commit -- $'\xff'", """git push origin "$'-f'" """,
                    r"echo $'\xff'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_ansi_c_inside_nested_bodies(self):
        inner = r"git push $'-f'"
        for cmd in [shell_c(inner), 'eval ' + shlex.quote(inner), f'echo $({inner})', f'echo `{inner}`',
                    shell_c(shell_c(inner)), 'eval "git push $\'\\x2df\'"', f'echo <({inner})']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)
        self.assertAsk(shell_c(r"git push $'\xff'"))

    def test_locale_quoted_words_are_double_quoted_words(self):
        for cmd in ['git push $"-f"', 'git push origin $"+main"', 'git commit $"-n" -m x', 'git $"push" -f',
                    shell_c('git push $"-f"')]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)
        self.assertEqual(forms('git commit -m $"a -n"'), [])
        self.assertEqual(forms('git push origin "$"'), [])

    def test_brace_expansion_is_expanded_and_each_word_judged(self):
        for cmd in ['git push origin {+main,x}', 'git push {-f,x}', 'git push --forc{e,}', 'git push -{f,u}',
                    'git push -o {x,-f}', 'git commit -m {x,-n}', 'git {push,x} -f', '{git,push,-f}', 'git push origin :{a,b}',
                    'git push origin {a,{+b,c}}', 'git commit {-n,x} -m y', 'git push {,-f}', '{sudo,env} git push -f',
                    'git push "x" {+main,}', 'git commit -m x {-n,}', 'git push origin {1..3} {+x,y}', 'git push -{f,}']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_brace_or_zsh_equals_in_the_word_that_names_the_shell_or_prefix(self):
        for cmd in ["{sh,-c} 'git " + PUSH_F + "'", "{eval,git} " + PUSH_F[:4] + ' -' + 'f', "{env,-S} 'git " + PUSH_F + "'",
                    "=bash -c 'git " + PUSH_F + "'", "=env -S 'git " + PUSH_F + "'", "=sudo =git " + PUSH_F,
                    "{bash,-c} \"git " + PUSH_F + "\"", "{sudo,-n} git " + PUSH_F]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_brace_expansion_inside_nested_bodies(self):
        inner = 'git push origin {+main,x}'
        for cmd in [shell_c(inner), 'eval ' + shlex.quote(inner), f'echo $({inner})', 'eval git push origin {+main,x}',
                    f'echo <({inner})']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_brace_words_that_expand_to_nothing_dangerous_pass(self):
        for cmd in ['git push origin {1..3}', 'git push origin HEAD:refs/heads/{a,b}', 'git push origin {x}',
                    'git push origin {}', 'git push origin {a..c}', 'git push origin {+main,x', 'git push origin HEAD@{u}',
                    'git commit -m x -- {a,b}.txt', 'git commit -m {a,b}', "git push origin 'x{a,b}'",
                    'git push origin "{+main,x}"', "git commit -m '{x,-n}'", 'git commit -m "{x,-n}"',
                    'git push origin {a,b}:{c,d}', 'git push origin x{1..3}y', 'git push -u origin {a,b}',
                    'git commit -m "x" -- {a,b}', 'echo git push {+a,b}', 'find . -exec echo {} +', 'git push origin ^{commit}',
                    r'git push origin \{+main,x\}', 'git push origin {x,y}{,:old}', 'git push {a,b}{-f,}']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [], cmd)

    def test_brace_word_that_cannot_be_expanded_is_an_ask(self):
        self.assertAsk('git push {1..100}', '{1..100}')
        self.assertAsk('git commit -m {1..100}', '{1..100}')
        self.assertAsk('git push origin {a..z}{a..z}{a..z}', '{a..z}{a..z}{a..z}')
        self.assertAsk(shell_c('git push {1..100}'), '{1..100}')

    def test_process_substitution_bodies_are_judged(self):
        for cmd in ['echo <(git ' + PUSH_F + ')', 'echo >(git ' + PUSH_F + ')', 'cat <(echo a) <(git push origin +main)',
                    'diff <(git log) <(git commit -n -m x)', shell_c('echo <(git ' + PUSH_F + ')'),
                    'tee >(git push --mirror) < f', 'cat < <(git ' + PUSH_F + ')', 'echo x>(git ' + PUSH_F + ')',
                    'echo =(git ' + PUSH_F + ')', 'echo $(echo <(git ' + PUSH_F + '))',
                    'echo <(echo <(git ' + PUSH_F + '))', 'sh -c "echo <(git ' + PUSH_F + ')"']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_process_substitution_in_a_slot_is_an_ask(self):
        self.assertAsk('git push origin <(echo x)', '<(echo x)')
        self.assertAsk('git commit >(cat) -m x', '>(cat)')
        self.assertEqual(forms('git commit -m "$(cat <(echo m))"'), [])
        self.assertEqual(forms('git commit -F <(echo m)'), [])

    def test_process_substitution_look_alikes_are_text(self):
        for cmd in ['echo "<(git ' + PUSH_F + ')"', "echo '<(git push --force)'", 'echo a\\<(b', 'x=(git status)',
                    'cat <(git status)', 'git commit -m "x <(y)"', 'echo "=(git push --force)"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_parameter_default_that_spells_an_option_is_an_ask(self):
        self.assertAsk('git push ${X:--' + 'f}', '${X:--f}')
        for cmd in ['git push ${1:--' + 'f}', 'git push ${@:--f}', 'git push ${X[0]:--f}', 'git push ${!X:--f}', 'git push ${*:+-f}',
                    'git push ${X:+-' + 'f}', 'git push ${X-+main}', 'git push origin "${B:=+main}"', 'git push ${X/a/-f}',
                    'git push ${X:?-f}', shell_c('git push ${X:--f}')]:
            with self.subTest(cmd=cmd):
                self.assertEqual(verdicts(cmd), ['ask'])

    def test_substitution_inside_a_parameter_word_is_still_judged(self):
        for cmd in ['echo ${X:--$(git ' + PUSH_F + ')}', 'echo ${X:-$(git ' + PUSH_F + ')}', 'echo "${X:-$(git ' + PUSH_F + ')}"']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)
        self.assertAsk('git push origin ${B:-$(git branch)}', '$(git branch)')

    def test_plain_and_ordinary_parameter_words_are_not_judged(self):
        for cmd in ['git push ${X}', 'git push origin "${B:-main}"', 'git push "${B:-origin}" ${R:-main}', 'git push ${#X}',
                    'git commit -m "${M:--n}"', 'git push --push-option "${O:--f}"', 'git push origin ${B%%/*}', 'git push $X',
                    'git push origin -- "${B:--f}"', "git push origin '${B:--f}'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_glob_word_that_can_name_an_option_is_an_ask(self):
        for cmd in ['git push -?', 'git push *', 'git push [-]f', 'git push origin *', 'git push --forc?', 'git push -[u]',
                    'git commit ?n -m x', shell_c('git push -?')]:
            with self.subTest(cmd=cmd):
                self.assertIn('ask', verdicts(cmd))

    def test_quoted_text_with_a_glob_is_not_asked(self):
        for cmd in ['git commit -m"[skip ci] x"', 'git commit -am"what? ok"', 'git push -o"a *" origin', 'git commit "[wip] *" x',
                    'git commit -m x "-* note"', 'git push "*.txt files"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_other_glob_and_tilde_words_pass(self):
        for cmd in ['git push origin refs/heads/*', 'git commit -m x src/*.py', 'git commit -m "[wip] *"', 'git push origin ~',
                    'git push ~/r', 'git commit -m x -- *.py', 'git push origin main?', 'git push --push-option=* origin',
                    'git commit -m x file[12].txt', 'git push -o "*" origin', 'git push --repo ~ origin main']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_git_word_spelled_with_quotes_escapes_or_zsh_equals(self):
        for cmd in ["g''it push -" + 'f', '\\git push -' + 'f', '"git" push -' + 'f', "'git' push -" + 'f', 'g\\it push -' + 'f',
                    '=git push -' + 'f', '=sudo git push -' + 'f', 'command \\git push -' + 'f', '/usr/bin/git push -' + 'f',
                    'git push -\\\n' + 'f', 'git pu\\\nsh -' + 'f', 'git push -"' + 'f"', "git push '-'f", 'git push -\\' + 'f',
                    'sh -c "git push -\\\\\n' + 'f"', "sh -c 'git push -\\\n" + "f'"]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_shell_options_before_the_c_string(self):
        for cmd in ['bash -o pipefail -c "git ' + PUSH_F + '"', 'bash -O extglob -c "git ' + PUSH_F + '"',
                    'sh +o posix -c "git ' + PUSH_F + '"', 'bash --rcfile /dev/null -c "git ' + PUSH_F + '"',
                    'bash -eo pipefail -c "git ' + PUSH_F + '"', 'zsh -o errexit -c "git ' + PUSH_F + '"',
                    'bash -c -- "git ' + PUSH_F + '"', 'bash -x -o nounset -lc "git ' + PUSH_F + '"',
                    'bash -co pipefail "git ' + PUSH_F + '"']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)
        self.assertEqual(forms('bash -o pipefail -c "git status"'), [])
        self.assertEqual(forms('bash -o pipefail script.sh git push'), [])

    def test_env_split_string_runs_a_command(self):
        for cmd in ["env -S 'git " + PUSH_F + "'", "env -S'git " + PUSH_F + "'", "env --split-string='git " + PUSH_F + "'",
                    "sudo env -i -S 'git " + PUSH_F + "'", "env -S 'bash -c \"git " + PUSH_F + "\"'"]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)
        for cmd in ["env -S 'git status'", "echo env -S 'git " + PUSH_F + "'", "git commit -m 'env -S x'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_text_names_the_command_as_written(self):
        found = forms('git push origin {+main,x}')
        self.assertEqual(found[0].text, 'git push origin +main x')       # the words the shell makes
        for cmd in ['git push origin {+main,x} {1..100}', 'git push {a,b} "open', 'git push {a,b} "open ' + PUSH_F,
                    shell_c('git push {a,b} "open'), 'git push {+a,b} $(ls', 'git push {a,b}; sh -c "git commit {n,m} \'x"']:
            with self.subTest(cmd=cmd):
                self.assertNotIn(ma_bash.MARK, ''.join(f.text + f.form for f in forms(cmd)))
        self.assertEqual(verdicts('git push {a,b} "open'), ['ask'])
        self.assertEqual(forms("git push $'-f'")[0].form, 'force push (`-f`)')


class CommandPositionTest(unittest.TestCase):
    """Criterion 1: a real push form in every place the shell puts a word in command position: after the reserved words
    and the headers of function, coproc and zsh forms, after the prefix words and the precommand modifiers, and in the
    string a builtin runs (`trap`, `eval`). What the check does not read is pinned in `test_the_remaining_limits`."""

    def assertDeny(self, cmd):
        self.assertIn('deny', verdicts(cmd), cmd)

    def test_function_keyword_with_or_without_parentheses(self):
        for cmd in ['function g { ' + GIT_F + '; }', 'function g() { ' + GIT_F + '; }', 'function g ( ) { ' + GIT_F + '; }',
                    'function g\n{\n' + GIT_F + '\n}', 'function g { true; ' + GIT_F + '; }', 'function a b { ' + GIT_F + '; }',
                    'function { ' + GIT_F + '; }', 'function g if true; then ' + GIT_F + '; fi',
                    'function g ' + GIT_F, 'f() { ' + GIT_F + '; }', 'f() ' + GIT_F,
                    shell_c('function g { ' + GIT_F + '; }; g'), 'echo $(function g { ' + GIT_F + '; })',
                    'echo <(function g { ' + GIT_F + '; })']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_coproc_with_or_without_a_name(self):
        for cmd in ['coproc ' + GIT_F, 'coproc X { ' + GIT_F + '; }', 'coproc { ' + GIT_F + '; }', 'coproc X ( ' + GIT_F + ' )',
                    'coproc X if true; then ' + GIT_F + '; fi', 'coproc X while ' + GIT_F + '; do true; done',
                    shell_c('coproc ' + GIT_F), 'echo $(coproc ' + GIT_F + ')']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_reserved_words_and_compound_commands(self):
        for cmd in ['! ' + GIT_F, 'true && ! ' + GIT_F, 'time ' + GIT_F, 'time -p ' + GIT_F, 'time -p -- ' + GIT_F,
                    'time -f %e ' + GIT_F, 'time -o t.txt ' + GIT_F, 'time ! ' + GIT_F,
                    'if true; then ' + GIT_F + '; fi', 'if false; then true; else ' + GIT_F + '; fi',
                    'if false; then true; elif ' + GIT_F + '; then true; fi', 'if ' + GIT_F + '; then true; fi',
                    'while ' + GIT_F + '; do true; done', 'until ' + GIT_F + '; do true; done',
                    'for i in 1 2; do ' + GIT_F + '; done', 'select i in 1; do ' + GIT_F + '; done',
                    'case x in x) ' + GIT_F + ';; esac', 'case x in a|b) true;; *) ' + GIT_F + ';; esac',
                    '{ ' + GIT_F + '; }', '( ' + GIT_F + ' )', '{ true; } && { ' + GIT_F + '; }',
                    'if true; then { ' + GIT_F + '; }; fi']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_zsh_forms(self):
        for cmd in ['if true { ' + GIT_F + ' }', 'while true { ' + GIT_F + ' }', 'for x in a b { ' + GIT_F + ' }',
                    'for x (a b) ' + GIT_F, 'for x (a b) { ' + GIT_F + ' }', 'foreach x (a b)\n' + GIT_F + '\nend',
                    '{ true } always { ' + GIT_F + ' }', '() { ' + GIT_F + ' }', 'repeat 2 ' + GIT_F, 'repeat $n ' + GIT_F,
                    'noglob ' + GIT_F, 'nocorrect ' + GIT_F, '- ' + GIT_F, 'noglob nocorrect command ' + GIT_F]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_prefix_builtins_and_their_options(self):
        for cmd in ['exec ' + GIT_F, 'exec -a name ' + GIT_F, 'exec -cla name ' + GIT_F, 'exec -c ' + GIT_F,
                    'command ' + GIT_F, 'command -p ' + GIT_F, 'builtin ' + GIT_F, 'command exec ' + GIT_F,
                    'nohup ' + GIT_F, 'env -i A=b ' + GIT_F, 'timeout 5 ' + GIT_F, 'nice -n 5 ' + GIT_F,
                    '>out ' + GIT_F, '2>&1 ' + GIT_F, 'A=b ' + GIT_F]:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)

    def test_trap_and_eval_run_a_string(self):
        for cmd in ["trap '" + GIT_F + "' EXIT", 'trap "' + GIT_F + '" EXIT INT', "trap -- '" + GIT_F + "' EXIT",
                    "trap -p '" + GIT_F + "' EXIT", "builtin trap '" + GIT_F + "' ERR",
                    'eval "' + GIT_F + '"', 'eval ' + GIT_F, 'command eval "' + GIT_F + '"',
                    shell_c("trap '" + GIT_F + "' EXIT"), 'if true; then trap "' + GIT_F + '" EXIT; fi']:
            with self.subTest(cmd=cmd):
                self.assertDeny(cmd)
        for cmd in ['trap -p', 'trap -l', "trap '' INT", 'trap - EXIT', "trap 'echo bye' EXIT", 'trap EXIT']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_quoted_brace_and_plain_group_words_are_not_a_command_start(self):
        found = forms("git commit -m '{' " + NV)
        self.assertEqual([f.verdict for f in found], ['deny'])
        self.assertEqual(found[0].text, "git commit -m '{' " + NV)       # one command: the quoted brace is data
        for cmd in ['echo "{ ' + GIT_F + ' }"', "echo '{' x", 'git push origin {', 'git push origin { main',
                    'git push -o { main', 'git commit -m {', 'git commit -m { x', 'git commit -am { x',
                    'echo { git push }', 'function g { true; }', 'coproc X { true; }', 'time -p true', 'repeat 2 true']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])
        self.assertEqual(verdicts('git push origin { ' + FORCE), ['deny'])      # the word after `{` is judged

    def test_the_remaining_limits(self):
        """Named in 4.4 as not judged: the string is no word of a command the tokenizer can see, or the program that
        runs it is not on its list. Each gives no verdict; a change that reads one must change the limits sentence."""
        quoted = shlex.quote(GIT_F)
        for cmd in ['stdbuf -oL ' + GIT_F, 'ionice -c 3 ' + GIT_F, 'caffeinate ' + GIT_F, 'watch ' + GIT_F,
                    'find . -exec ' + GIT_F + ' \\;', 'ssh host ' + quoted, 'su -c ' + quoted, 'parallel ::: ' + quoted,
                    'fish -c ' + quoted, 'busybox sh -c ' + quoted,
                    'alias gp=' + quoted + '; gp', 'PROMPT_COMMAND=' + quoted, 'bind -x ' + shlex.quote('"\\C-x": ' + GIT_F),
                    'echo ' + quoted + ' | sh', 'sh <<< ' + quoted, 'sh <<EOF\n' + GIT_F + '\nEOF',
                    'source <(echo ' + quoted + ')', 'echo ' + quoted + ' > s.sh; sh s.sh', 'X=' + quoted + '; $X']:
            with self.subTest(cmd=cmd):
                self.assertEqual(forms(cmd), [])

    def test_text_has_no_group_token(self):
        text = 'git ' + PUSH_F
        for cmd in ['f() { ' + text + '; }', '{ ' + text + '; }', '( ' + text + ' )', '! ' + text,
                    'if true; then ' + text + '; fi', 'while ' + text + '; do true; done', 'if true { ' + text + ' }',
                    'function g { ' + text + '; }', '{ ' + text + ' }', text]:
            with self.subTest(cmd=cmd):
                self.assertEqual([f.text for f in forms(cmd)], [text])
        self.assertEqual([f.text for f in forms('time -p ' + text)], ['time -p ' + text])
        found = forms('{ GIT_CONFIG_KEY_0=core.hooksPath git status; }')
        self.assertEqual([f.text for f in found], ['GIT_CONFIG_KEY_0=core.hooksPath git status'])


class LoneBraceTest(unittest.TestCase):
    """Criteria 1 and 2: an unquoted lone `{` is a command start only where a compound command can begin (the start of
    a simple command, after `function NAME`, `coproc [NAME]`, `repeat N`, the words of a zsh short form, `} always`).
    After a command word it is an argument, so the words after it are judged as part of that command and a plain
    mention (`echo { git push -f }`) is no command. Where the two cannot be told apart both readings are judged."""

    def assertDenyAll(self, cmds):
        for cmd in cmds:
            for wrapped in (cmd, shell_c(cmd), 'echo $(' + cmd + ')'):
                with self.subTest(cmd=wrapped):
                    self.assertIn('deny', verdicts(wrapped))

    def assertNone(self, cmds):
        for cmd in cmds:
            for wrapped in (cmd, shell_c(cmd), 'echo $(' + cmd + ')'):
                with self.subTest(cmd=wrapped):
                    self.assertEqual(forms(wrapped), [])

    def test_a_lone_brace_as_a_value_or_argument_leaves_the_words_after_it_judged(self):
        self.assertDenyAll([
            'git commit -m { -n', 'git commit -m { ' + NV, 'git commit -am { ' + NV, 'git commit -am { -n',
            'git commit -m { -a -n', 'git commit -m x { -n', 'git commit -m x { ' + NV,
            'git push origin main -o { ' + FORCE, 'git push -o { --' + 'force origin main', 'git push -o { ' + FORCE,
            'git push origin { ' + FORCE, 'git push origin main { ' + FORCE, 'git push origin { --' + 'force',
            'git push origin { +main', 'git push --repo { ' + FORCE, 'git -C { commit -n', 'git -c { commit -n',
            'git -C /r commit -m { -n', 'sudo git commit -m { -n', 'A=b git commit -m { -n'])
        self.assertEqual(verdicts('git commit -m { -n "open'), ['deny'])      # the unparsed scan reads it the same way
        self.assertEqual(verdicts('git push origin main -o { ' + FORCE + ' "open'), ['deny'])

    def test_a_lone_brace_after_a_prefix_option_that_takes_a_value_is_that_value(self):
        self.assertDenyAll(['env -u { -i ' + GIT_F, 'exec -a { -l ' + GIT_F, 'sudo -u { ' + GIT_F, 'timeout { ' + GIT_F,
                            'nice -n { ' + GIT_F, 'time -f { ' + GIT_F])

    def test_a_plain_mention_with_a_brace_is_no_command(self):
        self.assertNone(['echo { ' + GIT_F + ' }', 'echo { git commit -n }', 'echo { git commit ' + NV + ' }',
                         'printf { ' + GIT_F, 'echo x { ' + GIT_F, 'echo { ' + GIT_F + ' ;',
                         'git push origin {', 'git push origin { main', 'git commit -m {', 'git commit -m { x',
                         'git status { ' + PUSH_F])

    def test_a_group_start_is_still_read_where_a_command_can_start(self):
        self.assertDenyAll(['{ ' + GIT_F + '; }', 'true && { ' + GIT_F + '; }', 'if true; then { ' + GIT_F + '; }; fi',
                            '! { ' + GIT_F + '; }', 'time { ' + GIT_F + '; }', 'sudo { ' + GIT_F + '; }',
                            'function g { ' + GIT_F + ' }', 'function g { ' + GIT_F + '; }', 'function { ' + GIT_F + ' }',
                            'g() { ' + GIT_F + ' }', 'g () { ' + GIT_F + ' }', 'function g() { ' + GIT_F + ' }',
                            'coproc { ' + GIT_F + ' }', 'coproc X { ' + GIT_F + ' }', 'repeat 2 { ' + GIT_F + ' }',
                            'for x (a b) { ' + GIT_F + ' }', 'for x in a b { ' + GIT_F + ' }',
                            'foreach x { ' + GIT_F + ' }', 'select x in a { ' + GIT_F + ' }',
                            '{ true } always { ' + GIT_F + ' }',
                            '{ true; } always { ' + GIT_F + '; }'])

    def test_case_body_after_a_brace(self):
        self.assertIn('deny', verdicts('case x { x) ' + GIT_F + ' }'))

    def test_zsh_short_forms_with_a_condition_are_read_both_ways(self):
        self.assertDenyAll(['if true { ' + GIT_F + ' }', 'while true { ' + GIT_F + ' }', 'until true { ' + GIT_F + ' }',
                            'if [[ -n x ]] { ' + GIT_F + ' }', 'if (( 1 )) { ' + GIT_F + ' }',
                            'if true; [[ -n x ]] { ' + GIT_F + ' }', 'if true; echo x { ' + GIT_F + ' }',
                            'if ! true { ' + GIT_F + ' }', 'if true; then true; elif true { ' + GIT_F + ' }',
                            'function a b { ' + GIT_F + ' }', 'if true { true } elif true { ' + GIT_F + ' }'])
        # the condition is itself a git command with a lone brace: the bash reading judges the words after the brace
        self.assertDenyAll(['if git commit -m { -n; then true; fi', 'while git commit -m { -n; do true; done',
                            'if git push origin { ' + FORCE + '; then true; fi', 'function g git commit -m { -n',
                            'if git commit -m { -n { true }', 'if ! git commit -m { -n; then true; fi'])

    def test_a_closing_brace_is_a_word_or_the_end_of_a_group(self):
        self.assertDenyAll(['git push origin } ' + FORCE, 'git commit -m } -n', 'git push origin } { ' + FORCE,
                            'function g { git push origin } ' + FORCE + ' }', 'function g { ' + GIT_F + ' }',
                            'if true { true } else { ' + GIT_F + ' }', 'if true { true; } else { ' + GIT_F + '; }',
                            'if true { ' + GIT_F + ' } else { true }', 'if true { git push origin main } else { git commit -n }',
                            'if true { true } elif true { ' + GIT_F + ' } else { true }',
                            '{ git push origin main } always { git commit -n }',
                            '{ git push origin main; } always { git commit -n; }',
                            'function g { true } ; ' + GIT_F, 'function g { true }\n' + GIT_F])
        self.assertNone(['echo x } always { ' + GIT_F + ' }', 'echo } ' + GIT_F, 'git push origin } main'])

    def test_the_false_denies_that_remain_are_these(self):
        """Named in 4.4. The zsh short forms are read where bash reads an argument, and a lone `}` after a command in an
        open group is read as its closer as well: a line of these shapes that only prints text is denied."""
        for cmd in ['if echo { ' + GIT_F + ' }; then true; fi', 'for x in a { ' + GIT_F, 'while echo { ' + GIT_F,
                    '{ echo } ' + GIT_F + '; }']:
            with self.subTest(cmd=cmd):
                self.assertIn('deny', verdicts(cmd))

    def test_text_names_the_command_once(self):
        for cmd in ['if true { ' + GIT_F + ' }', 'function g { ' + GIT_F + ' }', 'time { ' + GIT_F + '; }',
                    'coproc X { ' + GIT_F + ' }', '{ true } always { ' + GIT_F + ' }',
                    'if true { true } else { ' + GIT_F + ' }', 'env -u { ' + GIT_F, 'echo $(function g { ' + GIT_F + ' })']:
            with self.subTest(cmd=cmd):
                self.assertEqual([f.text for f in forms(cmd)], [GIT_F if 'env' not in cmd else "env -u '{' " + GIT_F])

    def test_many_groups_and_odd_braces_end_in_time_and_in_a_verdict(self):
        many = 'if true { ' * 200 + GIT_F + ' }' * 200
        self.assertIn('deny', verdicts(many))
        self.assertEqual(verdicts('echo ' + '} ' * 3000 + GIT_F), [])        # nothing open: words of echo
        self.assertIn('deny', verdicts('git push ' + '} ' * 3000 + FORCE))
        self.assertEqual(verdicts('git ' + '{ ' * 3000 + 'push origin main'), [])
        found = verdicts('if true { x } ' * 80 + GIT_F)
        self.assertTrue(found and set(found) <= {'ask', 'deny'})            # too many readings is a command that does not parse


if __name__ == '__main__':
    unittest.main()
