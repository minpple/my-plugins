"""lib/ma_bash: which paths a Bash command writes, reads, or copies from (architecture 4.4 "what is blocked")."""
import shlex
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts lib/ on sys.path)
import ma_bash

CWD = Path('/p')


def P(s):
    return Path(s).resolve()


class WriteTargetsTest(unittest.TestCase):
    def test_read_paths_cd_checks_both_folders(self):
        got = ma_bash.read_paths('cd sub; cat ../x', CWD)
        self.assertIn(P('/p/x'), got)   # the cd worked
        self.assertIn(P('/x'), got)     # the cd failed

    def test_bash_write_targets_table(self):
        table = [
            ('ls -la', []),
            ('cat a > out.txt', [P('/p/out.txt')]),
            ('echo x >> /tmp/l', [P('/tmp/l')]),
            ('cmd 2>&1 | tail -3', []),
            ('cmd >/dev/null 2>&1', []),
            ('cmd 2>/dev/null', []),
            ("sed -i '' 's/a/b/' f.md", [P('/p/f.md')]),
            ('sed -n 1,5p f.md', []),
            ('printf x | tee -a docs/agent/t/run-log.md', [P('/p/docs/agent/t/run-log.md')]),
            ('mkdir -p docs/agent/t && cp -pR a b/', [P('/p/docs/agent/t'), P('/p/b')]),
            ('rm -rf build', [P('/p/build')]),
            ('touch a; mv x y', [P('/p/a'), P('/p/y')]),
            ('dd if=/dev/zero of=img bs=1', [P('/p/img')]),
            ('git checkout -- x', None),
            ('git -C sub stash', None),
            ('git status --porcelain', []),
            ('git diff HEAD', []),
            ('python3 run-log.py step n=1A', []),
            ('FOO=1 sudo rm x', [P('/p/x')]),
            ('find . -name "*.pyc" -delete', None),
            ('ls | xargs rm', None),
            ('echo hi > "$OUT"', None),
            ("cat > f.txt <<'EOF'\nrm -rf /\nEOF", [P('/p/f.txt')]),
            ('ls\nrm z', [P('/p/z')]),
            ('cat ~/notes.md', []),
        ]
        for cmd, expected in table:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), expected)

    def test_unparseable_quotes_is_none(self):
        self.assertIsNone(ma_bash.write_targets('echo "unterminated > x', CWD))


class FinalReviewGapsTest(unittest.TestCase):
    """Forms the final review found the parser missed (I1, C3, I3, I4): each must name its target or give None."""

    def test_reserved_words_and_prefix_values(self):
        table = [
            ('if true; then rm -rf src; fi', [P('/p/src')]),
            ('for f in src/*.py; do sed -i "" s/a/b/ src/a.py; done', [P('/p/src/a.py')]),
            ('while read f; do rm src/a.py; done < list', [P('/p/src/a.py')]),
            ('{ rm -rf src; }', [P('/p/src')]),
            ('! rm src/a.py', [P('/p/src/a.py')]),
            ('sudo -u root rm src/a.py', [P('/p/src/a.py')]),
            ('nice -n 10 rm src/a.py', [P('/p/src/a.py')]),
            ('timeout 5 rm src/a.py', [P('/p/src/a.py')]),
        ]
        for cmd, expected in table:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), expected)

    def test_nested_shells_are_parsed(self):
        self.assertEqual(ma_bash.write_targets('bash -c "rm -rf src"', CWD), [P('/p/src')])
        self.assertEqual(ma_bash.write_targets("sh -ec 'touch a'", CWD), [P('/p/a')])
        self.assertEqual(ma_bash.write_targets('eval "rm -rf src"', CWD), [P('/p/src')])
        self.assertIn(Path.home() / '.ssh/id_rsa', ma_bash.read_paths('bash -c "cat ~/.ssh/id_rsa"', CWD))

    def test_substitution_and_open_heredoc_fail_closed(self):
        for cmd in ['echo `rm -rf src`', 'echo "$(rm -rf src)"', 'echo "<<EOF"\nrm -rf src']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))
                self.assertIsNone(ma_bash.read_paths(cmd, CWD))
        self.assertEqual(ma_bash.write_targets('cat <<< x\nrm -rf src', CWD), [P('/p/src')])

    def test_cd_is_followed(self):
        self.assertEqual(ma_bash.write_targets('cd src && touch docs/agent/x', CWD), [P('/p/src/docs/agent/x')])
        self.assertEqual(sorted(ma_bash.write_targets('cd src; touch docs/agent/x', CWD)),
                         sorted([P('/p/docs/agent/x'), P('/p/src/docs/agent/x')]))
        self.assertIn(P('/p/docs/agent/t/review.md'),
                      ma_bash.write_targets('cd docs && echo "BLOCKER 0" > agent/t/review.md', CWD))
        self.assertIsNone(ma_bash.read_paths('cd "$HOME" && cat .ssh/id_rsa', CWD))
        self.assertIsNone(ma_bash.write_targets('cd "$D" && touch x', CWD))
        self.assertIsNone(ma_bash.read_paths('cd "$D" && cat x', CWD))
        self.assertEqual(ma_bash.write_targets('cd src && pytest', CWD), [])

    def test_symlink_with_another_write_is_none(self):
        self.assertIsNone(ma_bash.write_targets('ln -s docs/agent/t x && echo 0 > x/review.md', CWD))
        self.assertEqual(ma_bash.write_targets('ln -s a b', CWD), [P('/p/b')])

    def test_variable_paths_make_reads_unknown(self):
        self.assertIsNone(ma_bash.read_paths('cat $HOME/.ssh/id_rsa', CWD))
        self.assertIsNone(ma_bash.read_paths('ln -s "$HOME/.zshrc" z', CWD))
        self.assertEqual(ma_bash.read_paths('echo $PATH', CWD), [])


class SingleQuoteTest(unittest.TestCase):
    """Single-quoted `$(` and backticks are literal; unquoted and double-quoted ones stay unknown."""

    def test_single_quoted_substitution_is_text(self):
        for cmd, read in [("grep -rn 'foo$(bar' src/", '/p/src'), ("grep -n 'a`b' src/a.py", '/p/src/a.py'),
                          ("grep -rn '\\$(x)' src/", '/p/src')]:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), [])
                self.assertEqual(ma_bash.read_paths(cmd, CWD), [P(read)])
        self.assertEqual(ma_bash.read_paths("grep -rn 'x$(y)' src/", CWD), [P('/p/src')])
        self.assertEqual(ma_bash.write_targets("grep 'x`y`' a > out.txt", CWD), [P('/p/out.txt')])

    def test_other_substitution_is_unknown(self):
        for cmd in ['echo "$(date)"', 'echo $(date)', 'echo `date`', 'echo "`date`"', "echo 'a' $(date)",
                    'echo "it\'s" $(date)', 'echo x | grep "$(cat f)"']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))
                self.assertIsNone(ma_bash.read_paths(cmd, CWD))

    def test_nested_shell_strings_stay_unknown(self):
        self.assertIsNone(ma_bash.write_targets("bash -c 'echo $(date)'", CWD))
        self.assertIsNone(ma_bash.write_targets("eval 'rm `x`'", CWD))
        self.assertEqual(ma_bash.write_targets("bash -c 'grep \"a\" f'", CWD), [])


class HeredocTest(unittest.TestCase):
    """Any delimiter word closes at its matching line; the body is not read as commands."""

    def test_delimiter_words(self):
        for delim in ['EOF.txt', 'END-EXPLORE', "'EOF-1'", '"EOF.txt"', 'EOF', 'E1']:
            word = delim.strip('\'"')
            cmd = f'cat > f.txt <<{delim}\nrm -rf /\ngit commit -m x\n{word}\nls'
            with self.subTest(delim=delim):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), [P('/p/f.txt')])
                self.assertEqual(ma_bash.git_subcommands(cmd), [])
        self.assertEqual(ma_bash.write_targets('cat <<-EOF.txt\n\trm x\n\tEOF.txt', CWD), [])

    def test_unclosed_still_fails_closed(self):
        for cmd in ["cat <<'EOF-1'\nbody", 'cat <<EOF.txt\nbody\nEOF']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))
        self.assertEqual(ma_bash.git_subcommands("cat <<'EOF-1'\nbody"), [])

    def test_body_after_quoted_delimiter_not_commands(self):
        self.assertEqual(ma_bash.git_subcommands("cat <<'EOF-1'\ngit commit -m x\nEOF-1"), [])
        self.assertEqual(ma_bash.git_subcommands("cat <<'EOF-1' && git add a\nx\nEOF-1"), ['add'])


class HeredocExpansionTest(unittest.TestCase):
    """An unquoted heredoc expands its body in the current shell; a quoted one is literal."""

    def test_substitution_in_unquoted_body_is_unknown(self):
        for cmd in ['cat <<EOF\n$(rm x)\nEOF', 'cat <<EOF\n`rm x`\nEOF', 'cat <<-EOF\n\t$(rm x)\n\tEOF',
                    'cat <<EOF\nok\nEOF\ncat <<EOF2\n$(rm x)\nEOF2']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))
                self.assertIsNone(ma_bash.read_paths(cmd, CWD))

    def test_quoted_delimiters_keep_the_body_literal(self):
        for delim in ["'EOF'", '"EOF"', '\\EOF']:
            cmd = f'cat <<{delim}\n$(rm x) `rm x` ${{D:=/etc}}\nEOF'
            with self.subTest(delim=delim):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), [])

    def test_commit_with_heredoc_still_unparsed(self):
        for cmd in ['git commit -m "$(cat <<\'EOF\'\nfeat\nEOF\n)"', 'git commit -m "$(cat <<EOF\nfeat $x\nEOF\n)"',
                    'git commit -m "$(cat <<EOF\nfeat\nEOF\n)"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.git_subcommands(cmd), ['?'])


class CdTest(unittest.TestCase):
    """`cd x &&` resolves against x only; anything else keeps the old folder as well."""

    def test_and_chain(self):
        self.assertEqual(ma_bash.write_targets('cd x && touch f', CWD), [P('/p/x/f')])
        self.assertEqual(ma_bash.write_targets('cd x && cd y && touch f', CWD), [P('/p/x/y/f')])
        self.assertEqual(ma_bash.write_targets('cd x && ( touch f )', CWD), [P('/p/x/f')])
        self.assertEqual(ma_bash.write_targets('cd x && bash -c "touch f"', CWD), [P('/p/x/f')])

    def test_not_replaced(self):
        both = sorted([P('/p/f'), P('/p/x/f')])
        for cmd in ['cd x; touch f', 'cd x || touch f', 'cd x\ntouch f', '( cd x && touch f ); touch f',
                    'cd x & touch f', 'cd x | touch f', 'false || cd x && touch f', 'if true; then cd x && true; fi; touch f']:
            with self.subTest(cmd=cmd):
                self.assertTrue(set(both) <= set(ma_bash.write_targets(cmd, CWD)))
        self.assertEqual(sorted(ma_bash.write_targets('cd x; touch f', CWD)), both)
        self.assertEqual(sorted(ma_bash.write_targets('cd x || touch f', CWD)), both)

    def test_after_the_and_chain_both_folders(self):
        both = sorted([P('/p/f'), P('/p/x/f')])
        for cmd in ['cd x && true; touch f', 'cd x && true || touch f', 'cd x && true\ntouch f',
                    'cd x && true & touch f']:
            with self.subTest(cmd=cmd):
                self.assertEqual(sorted(ma_bash.write_targets(cmd, CWD)), both)

    def test_unknown_stays_unknown(self):
        self.assertIsNone(ma_bash.write_targets('cd "$D" && touch f', CWD))
        self.assertIsNone(ma_bash.write_targets('cd - && touch f', CWD))

    def test_read_paths_follow_the_same_rule(self):
        self.assertEqual(ma_bash.read_paths('cd x && cat a/b', CWD), [P('/p/x/a/b')])
        self.assertEqual(sorted(ma_bash.read_paths('cd x; cat a/b', CWD)), sorted([P('/p/a/b'), P('/p/x/a/b')]))


class VariableTest(unittest.TestCase):
    """`NAME=literal` is followed only when one closed rule holds (architecture 4.4); every other use stays unknown."""

    def test_unfollowed_variable_paths_are_unknown(self):
        for cmd in ['P=/a; P=/b; cat $P/x', 'P=$(pwd); cat $P/x', 'cat $P/x; P=/a', 'P=/a cat $P/x', 'cat $HOME/x',
                    'P=~/x; cat $P/y', 'false && P=/a; cat $P/x', 'ls /y && P=/a; cat $P/x',
                    'true || P=/a; cat $P/x', '(P=/a); cat $P/x', 'P=/a; export P=/etc; cat $P/x',
                    'P=/a; read P; cat $P/x', 'P=/a; P+=b; cat $P/x', 'P=/a; printf -v P /etc; cat $P/x',
                    'P=/a; printf -vP /etc; cat $P/x', 'P="/a /etc"; cat $P/passwd', "P=/a; bash -c 'cat $P/x'",
                    'P=/a; eval "cat $P/x"', 'P=/a; cat ${P:-/etc}/x', "P=/a; cat '$P'/x", 'IFS=/; P=/a; cat $P/x',
                    'P=/a; cat \\$P/x', 'P=/a; export Q=1; cat $P/x', 'P=/a; for P in /etc; do cat $P/x; done',
                    'P=/a\ncat $P/x | head; P=/b', 'P=/a *; cat $P/x',
                    'P=a*; cat $P/x', 'P=/a; (cat $P/x)  ; unset P; cat $P/y', 'P=/a & cat $P/x',
                    'PWD=/tmp; cd /etc; cat $PWD/x', 'OLDPWD=/a; cd /b; cat $OLDPWD/x', 'PWD=/tmp; cat ${PWD}/x',
                    'RANDOM=1; cat $RANDOM/x', 'SECONDS=1; cat $SECONDS/x',
                    '_=/a; cat $_/x', 'BASH_ARGV0=/a; cat $BASH_ARGV0/x']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.read_paths(cmd, CWD))
        for cmd in ['P=/a; P=/b; echo hi > $P/x', 'false && P=/a; echo hi > $P/x', 'P=/a; export P=/etc; rm $P/x',
                    'echo hi > $HOME/x', 'D=~/x; echo hi > $D/f', 'D=/x; ls; cd $E && touch f']:
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))

    def test_literal_variable_expands(self):
        for cmd in ['D=/x/y; cat $D/f', 'D=/x/y\ncat ${D}/f', 'D=/x/y; cat "$D/f"', "D='/x/y'; cat $D/f",
                    'D=/x/y; E=/z; cat $D/f']:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.read_paths(cmd, CWD), [P('/x/y/f')])
        self.assertEqual(ma_bash.read_paths('D=..; cat $D/f', CWD), [P('/f')])
        self.assertEqual(ma_bash.write_targets('D=/x/y; echo hi > $D/f', CWD), [P('/x/y/f')])
        self.assertEqual(ma_bash.write_targets('D=/x/y && echo hi > "${D}/f"', CWD), [P('/x/y/f')])
        self.assertEqual(ma_bash.write_targets('D=/x; E=/y; rm $D/a $E/b', CWD), [P('/x/a'), P('/y/b')])
        self.assertEqual(ma_bash.write_targets('D=/x; ls; cd $D && touch f', CWD), [P('/x/f')])
        self.assertEqual(ma_bash.copy_sources('D=/x; cp $D/a /y', CWD), [P('/x/a')])

    def test_cd_to_a_literal_variable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp).resolve() / 'dir'
            d.mkdir()
            (d / 'x').write_text('')
            paths = ma_bash.read_paths(f'D={d} && cd "$D" && ls x', CWD)
            self.assertIn(d / 'x', paths)
            self.assertEqual(ma_bash.read_paths(f'P={d}; cat $P/x', CWD), [d / 'x'])
            self.assertEqual(ma_bash.read_paths(f'P={d}; cat ${{P}}/x', CWD), [d / 'x'])
            self.assertEqual(ma_bash.write_targets(f'P={d}; echo hi > $P/out', CWD), [d / 'out'])
            self.assertIsNone(ma_bash.read_paths(f'D={d} && cd "$E" && ls x', CWD))

    def test_hash_inside_a_word_is_not_a_comment(self):
        self.assertEqual(ma_bash.write_targets('echo ${#D}; rm /etc/x', CWD), [P('/etc/x')])
        self.assertEqual(ma_bash.write_targets('echo a#b; rm /etc/x', CWD), [P('/etc/x')])
        self.assertEqual(ma_bash.write_targets('echo a # b; rm /etc/x', CWD), [])


class ReadPathsTest(unittest.TestCase):
    def test_read_paths(self):
        self.assertIn(Path.home() / '.ssh/id_rsa', ma_bash.read_paths('cat ~/.ssh/id_rsa', CWD))
        self.assertIn(P('/p/src'), ma_bash.read_paths('grep -rn foo src/', CWD))
        self.assertIn(P('/etc/hosts'), ma_bash.read_paths('head -n 3 --file=/etc/hosts', CWD))

    def test_patterns_are_not_paths(self):
        paths = ma_bash.read_paths("grep -rn '^/api' src/ && sed 's/a/b/' x/y https://e.com/a", CWD)
        self.assertNotIn(P('/api'), paths)
        self.assertEqual(sorted(paths), sorted([P('/p/src'), P('/p/x/y')]))

    def test_unparseable_is_none(self):
        self.assertIsNone(ma_bash.read_paths('cat "x', CWD))


class SetsidTest(unittest.TestCase):
    def test_setsid_is_seen_through(self):
        self.assertEqual(ma_bash.write_targets('setsid cp a /etc/b', CWD), [P('/etc/b')])


class CopySourcesTest(unittest.TestCase):
    def test_copy_sources(self):
        self.assertEqual(ma_bash.copy_sources('cp -p docs/agent/t/work/note.md ~/notes/', CWD),
                         [P('/p/docs/agent/t/work/note.md')])
        self.assertEqual(ma_bash.copy_sources('mv a b c/', CWD), [P('/p/a'), P('/p/b')])
        self.assertEqual(ma_bash.copy_sources('ls a', CWD), [])

    def test_copy_sources_follow_cd(self):
        self.assertEqual(ma_bash.copy_sources('cd T && cp work/f ~/out', CWD), [P('/p/T/work/f')])
        self.assertEqual(sorted(ma_bash.copy_sources('cd T; cp work/f ~/out', CWD)),
                         sorted([P('/p/work/f'), P('/p/T/work/f')]))
        self.assertEqual(ma_bash.copy_sources('cd "$D" && cp work/f ~/out', CWD), [P('/p/work/f')])
        self.assertEqual(ma_bash.copy_sources('D=/t; cp $D/f ~/out', CWD), [P('/t/f')])   # a literal variable
        self.assertEqual(ma_bash.copy_sources('cp $D/f ~/out', CWD), [])                # an unknown one


class GitSubcommandsTest(unittest.TestCase):
    def test_git_subcommands(self):
        self.assertEqual(ma_bash.git_subcommands('git add a && git -C x commit -m "m"; ls'), ['add', 'commit'])
        self.assertEqual(ma_bash.git_subcommands('echo "git commit"'), [])
        self.assertEqual(ma_bash.git_subcommands('git "unterminated'), ['?'])

    def test_split_words_still_have_the_shape(self):
        for cmd in ['git "c"ommit -m "$(x)"', "git 'com'mit -m \"$(x)\"", 'git co\\\nmmit -m "$(x)"',
                    '"g"it commit -m "$(x)"', 'g\\\nit commit -m "$(x)"', 'git comm\\it -m "$(x)"']:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.git_subcommands(cmd), ['?'])

    def test_unparsed_text_is_a_commit_only_with_the_shape(self):
        for cmd in ['echo git is a word "unclosed', 'echo "HEAD=$(git rev-parse HEAD)" && git status --porcelain',
                    'echo "$(git log)" ; echo commit', 'git status; echo "$(x)" commit', 'echo `date`; git status',
                    'echo "it is git" "$(x)" ; commit', 'ls "$(x)" | git log']:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.git_subcommands(cmd), [])
        self.assertEqual(ma_bash.git_subcommands('git -c a="x;y" commit'), ['commit'])   # parses; commit counts
        for cmd in ['git -C x commit -m "unclosed', 'git -C "$(a && b)" commit -m y', 'git "unclosed',
                    'git commit -m "$(cat <<\'EOF\'\nfeat\nEOF\n)"', 'x=$(a); git -C x commit -m m',
                    'git -C "$(a; b" commit', 'echo hi && git `x` commit', '(git commit -m "$(x)")']:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.git_subcommands(cmd), ['?'])


class EnvReadsTest(unittest.TestCase):
    def test_env_reads_table(self):
        table = [
            ('env', ['env']), ('env -i', ['env -i']), ('printenv', ['printenv']), ('printenv HOME', ['printenv HOME']),
            ('env | grep KEY', ['env']), ('true && printenv', ['printenv']), ('ls; set', ['set']),
            ('/usr/bin/env', ['/usr/bin/env']), ('command env', ['command env']), ('exec printenv', ['exec printenv']),
            ('nohup env', ['nohup env']), ('timeout 5 env', ['timeout 5 env']), ('FOO=1 env', ['FOO=1 env']),
            ('false || export', ['export']), ('export -p', ['export -p']), ('declare', ['declare']),
            ('typeset -p', ['typeset -p']), ('launchctl getenv PATH', ['launchctl getenv PATH']),
            ('cat /proc/1/environ', ['cat /proc/1/environ']), ('cat /proc/self/environ', ['cat /proc/self/environ']),
            ('cat /proc/$$/environ', ['cat /proc/$$/environ']),
            ('xargs -0 < /proc/self/environ', ['xargs -0 < /proc/self/environ']),
            ("bash -c 'printenv'", ['printenv']), ('env VAR=x printenv', ['env VAR=x printenv']),
            ('env -u HOME', ['env -u HOME']), ('sudo env', ['sudo env']), ('nice -n 5 env', ['nice -n 5 env']),
            ('env FOO=1', ['env FOO=1']), ('cat /proc/self/task/1/environ', ['cat /proc/self/task/1/environ']),
            ('bash -c "cat /proc/self/environ"', ['bash -c cat /proc/self/environ', 'cat /proc/self/environ']),
            ('env nohup', []),
            ('env -i cmd', []), ('env VAR=x cmd', []), ('command env VAR=x cmd', []), ('timeout 5 env -i cmd', []),
            ('set -e', []), ('set -o pipefail', []), ('export VAR=x', []), ('declare -x VAR=1', []),
            ('declare -p HOME', []), ('ls $HOME/x', []), ('echo $HOME', []), ('cat /proc/cpuinfo', []),
            ('launchctl list', []), ('echo env printenv', []), ('ls', []), ('echo "unclosed', []),
            ('echo $(printenv)', ['printenv']), ('echo `env`', ['env']), ('echo "$(printenv)"', ['printenv']),
            ('echo $(echo $(printenv))', ['printenv']), ('echo $(printenv HOME)', ['printenv HOME']),
            ('printenv $(date)', ['printenv $(date)']), ('echo $(date); env', ['env']), ('setsid env', ['setsid env']),
            ('setsid -f printenv', ['setsid -f printenv']),
            ('python3 -c "import os;print(os.environ)"', ['python3 -c import os;print(os.environ)']),
            ('python -c \'import os; os.environ.get("X")\'', ['python -c import os; os.environ.get("X")']),
            ('python3 -c "from os import environ; print(environ)"',
             ['python3 -c from os import environ; print(environ)']),
            ('python3 -Ic "import os; os.getenv(\'X\')"', ["python3 -Ic import os; os.getenv('X')"]),
            ('python3.12 -c "import os; os.environb"', ['python3.12 -c import os; os.environb']),
            ('echo "a $(env) b"', ['env']), ('echo $(date) $(env -i ls) `printenv`', ['printenv']),
            ('echo $(date)', []), ('echo $((1+2))', []), ('echo $((1+$(date)))', []),
            ('echo $(( $(printenv) ))', ['printenv']), ('python3 -c "print(1)"', []), ('setsid ls', []),
            ("echo '$(printenv)'", []), ('python3 script.py -c os.environ', []),
            ('echo $(printenv', ['printenv']), ('echo $(date', []),
        ]
        for cmd, expected in table:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.env_reads(cmd), expected)


class EnvReadsHeredocTest(unittest.TestCase):
    """The body of a quoted-delimiter heredoc is data (a note with a backticked `export`)."""
    BT = chr(96)

    def test_quoted_body_is_data(self):
        bt = self.BT
        cases = [
            f"cat > notes.md <<'EOF'\nuse {bt}export{bt} here\nEOF",
            "python3 - <<'EOF'\nexport\nEOF",
            f"cat << 'EOF'\n{bt}export{bt}\nEOF",
            f"cat <<-'EOF'\n\t{bt}export{bt}\n\tEOF",
            f'cat <<"EOF"\n{bt}export{bt}\nEOF',
            f"cat <<\\EOF\n{bt}export{bt}\nEOF",
            f"cat <<'EOF'\n$(printenv)\nEOF",
            f"cat <<'A' <<'B'\n{bt}export{bt}\nA\n{bt}env{bt}\nB",
            f"cat > a <<'EOF'\n{bt}export{bt}\nEOF\necho hi",
            f"python3 - <<'EOF'\nimport sys\nprint('{bt}export{bt}')\nEOF",
            f"cat <<'EOF' | wc -l\n{bt}export{bt}\nEOF",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.env_reads(cmd), [])

    def test_commands_around_the_body_are_still_read(self):
        bt = self.BT
        self.assertEqual(ma_bash.env_reads(f"cat <<'EOF'\n{bt}export{bt}\nEOF\nenv"), ['env'])
        self.assertEqual(ma_bash.env_reads("env <<'EOF'\nx\nEOF"), ['env'])

    def test_unquoted_body_keeps_substitution(self):
        bt = self.BT
        self.assertEqual(ma_bash.env_reads("cat <<EOF\n$(printenv)\nEOF"), ['printenv'])
        self.assertEqual(ma_bash.env_reads(f"cat <<EOF\n{bt}env{bt}\nEOF"), ['env'])
        self.assertEqual(ma_bash.env_reads(f'cat <<"EOF"\n$(printenv)\nEOF'), [])

    def test_heredoc_inside_quotes_is_not_trusted(self):
        bt = self.BT
        self.assertNotEqual(ma_bash.env_reads(f'bash -c "cat <<\'EOF\'\n{bt}export{bt}\nEOF"'), [])
        self.assertNotEqual(ma_bash.env_reads(f"echo \"<<'EOF'\"\n{bt}export{bt}\nEOF"), [])

    def test_here_string_is_not_a_heredoc(self):
        self.assertEqual(ma_bash.env_reads("cat <<< '$(printenv)'"), [])
        self.assertEqual(ma_bash.env_reads('cat <<< "$(printenv)"'), ['printenv'])


class GitRuleTest(unittest.TestCase):
    def test_git_rule_through_write_targets(self):
        for cmd in ('git commit -m x', 'git push', 'git -C a checkout b', 'git reset --hard', 'git add .',
                    'git branch -D x', 'git stash', 'ls && git restore f', 'git bisect start',
                    'git update-ref refs/heads/x HEAD', 'git notes add -m x', 'git fetch', 'git gc',
                    'git -c core.pager=x log', 'git diff --output=o.txt'):
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))
        for cmd in ('git status', 'git status --porcelain', 'git diff', 'git diff HEAD', 'git log --oneline',
                    'git log -3', 'git branch', 'git tag', 'git show HEAD', 'git show x', 'git stash list',
                    'git rev-parse HEAD', 'git -C sub rev-parse HEAD', 'git ls-files', 'git blame a'):
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), [])


class GitMvTest(unittest.TestCase):
    def test_targets(self):
        self.assertEqual(ma_bash.write_targets('git mv a b', CWD), [P('/p/a'), P('/p/b')])
        self.assertEqual(ma_bash.write_targets('cd src && git mv x y', CWD), [P('/p/src/x'), P('/p/src/y')])
        self.assertEqual(ma_bash.write_targets('export FOO=1; git mv a b', CWD), [P('/p/a'), P('/p/b')])

    def test_cannot_tell(self):
        for cmd in ('git mv a', 'git mv -k a b', 'git mv -- a b', 'git mv a b c', 'git mv $A b', 'git -C sub mv a b',
                    'echo docs/agent | xargs git mv a b', 'GIT_DIR=x git mv a b', 'GIT_WORK_TREE=/x git mv a b',
                    'env GIT_DIR=x git mv a b', 'env -C dir git mv a b', 'sudo git mv a b',
                    'export GIT_WORK_TREE=/outside; git mv a b', 'GIT_DIR=/x; git mv a b',
                    'declare -x GIT_DIR=/x && git mv a b', 'set -a; GIT_DIR=/x; git mv a b',
                    'typeset GIT_DIR=/x; git mv a b', '. ./env.sh; git mv a b',
                    'source env.sh && git mv a b'):
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))

    def test_unchanged(self):
        self.assertEqual(ma_bash.write_targets('echo x | xargs git status', CWD), [])
        for cmd in ('git add .', 'git commit -m x', 'git checkout b', 'git reset --hard'):
            with self.subTest(cmd=cmd):
                self.assertIsNone(ma_bash.write_targets(cmd, CWD))

    def test_empty_raw_fails_closed(self):
        c = ma_bash.Simple(['git', 'mv', 'a', 'b'], False, [], [])
        self.assertIsNone(ma_bash._writes(c))



class ReadPathsNotFilesTest(unittest.TestCase):
    """Arguments that are not files a command reads: devices, and the script or pattern of sed, awk and grep."""

    def test_devices_and_patterns_are_not_read_paths(self):
        cwd = Path('/proj')
        hosts = str(Path('/etc/hosts').resolve())  # /etc is a symlink to /private/etc on macOS
        for cmd, want in (
                ('npm ci </dev/null', []),
                ('diff /dev/null src/a.ts', ['/proj/src/a.ts']),
                ("sed -n '/export const M/,/as const/p' src/db.ts", ['/proj/src/db.ts']),
                ("cat src/db.ts | sed -n '/export const M/,/as const/p'", ['/proj/src/db.ts']),
                ("awk '/export const M/,/as const/' src/db.ts", ['/proj/src/db.ts']),
                ("awk -F / '/a/' src/db.ts", ['/proj/src/db.ts']),
                ("grep -rn '/home/ui' src/a.ts", ['/proj/src/a.ts']),
                ("grep -e x /etc/hosts", [hosts]),
                ("sed -n -e 1p /etc/hosts", [hosts]),
                ("grep -- /etc/a /etc/hosts", [hosts]),
                ("cat /etc/hosts", [hosts])):
            with self.subTest(cmd=cmd):
                self.assertEqual([str(p) for p in ma_bash.read_paths(cmd, cwd)], want)


def Q(code):
    return shlex.quote(code)


def iw(cmd):
    """interpreter_writes, checked to give what the inner reader gives: its catch-all must not hide a crash."""
    got = ma_bash._interpreter_writes(cmd, CWD)
    assert ma_bash.interpreter_writes(cmd, CWD) == got
    return got


class InterpreterWritesTest(unittest.TestCase):
    """`interpreter_writes` reads the inline code of python, node, ruby and perl (architecture 4.12 "Inline interpreter
    code"); only scope-guard calls it. A table row is (code, the files it writes under /p, or None)."""

    def rows(self, head, table):
        for code, names in table:
            with self.subTest(code=code):
                want = names if names is None else [P(n if n.startswith('/') else f'/p/{n}') for n in names]
                self.assertEqual(iw(head + Q(code)), want)

    def py(self, table):
        self.rows('python3 -c ', table)

    def node(self, table):
        self.rows('node -e ', [("const fs = require('fs'); " + c, n) for c, n in table])

    def rb(self, table):
        self.rows('ruby -e ', table)

    def pl(self, table):
        self.rows('perl -e ', table)

    def test_interpreter_inline_writes_table(self):
        table = [
            ('python3 -c ' + Q("open('o.txt','w')"), [P('/p/o.txt')]),
            ('python3 -c ' + Q("open('o.txt',mode='a')"), [P('/p/o.txt')]),
            ('python3 -c ' + Q("open('a.txt')"), []),
            ('python3 -c ' + Q("open('a','rb')"), []),
            ('python3 -c ' + Q("import json; json.load(open('a.json'))"), []),
            ('python3 -c ' + Q("import os; os.remove('a'); os.rename('b','c')"), [P('/p/a'), P('/p/b'), P('/p/c')]),
            ('python3 -c ' + Q("import shutil; shutil.rmtree('build')"), [P('/p/build')]),
            ('python3 -c ' + Q("from pathlib import Path; Path('x.md').write_text('y')"), [P('/p/x.md')]),
            ('python3 -c ' + Q("'a'.replace('a','b')"), []),
            ('python3 -c ' + Q("print(1)"), []),
            ('python3 -c ' + Q("open('/dev/null','w')"), []),
            ('node -e ' + Q("require('fs').writeFileSync('o','x')"), [P('/p/o')]),
            ('node -e ' + Q("console.log(1)"), []),
            ('ruby -e ' + Q("File.write('o','x')"), [P('/p/o')]),
            ('ruby -e ' + Q("FileUtils.rm_rf 'd'"), [P('/p/d')]),
            ('ruby -e ' + Q('puts "File.write is a method"'), []),
            ('perl -e ' + Q("open(my $f, '>', 'o')"), [P('/p/o')]),
            ('perl -e ' + Q("open(F, '>>log.txt')"), [P('/p/log.txt')]),
            ('perl -e ' + Q("open(F, '<', 'a')"), []),
            ('perl -e ' + Q("unlink 'a'"), [P('/p/a')]),
            ('perl -ne ' + Q("print if /open failed/"), []),
            ('cd sub && python3 -c ' + Q("open('o','w')"), [P('/p/sub/o')]),
            ('ls -la', []),
        ]
        for cmd, expected in table:
            with self.subTest(cmd=cmd):
                self.assertEqual(iw(cmd), expected)

    def test_interpreter_python_write_forms(self):
        self.py([
            ("open('o','w')", ['o']), ("open('o','a')", ['o']), ("open('o','x')", ['o']), ("open('o','r+')", ['o']),
            ("open('o','wb')", ['o']), ("open('o',mode='w')", ['o']), ("open(file='o',mode='w')", ['o']),
            ("open('o')", []), ("open('o','r')", []), ("open('o',mode='r')", []), ("open(p)", []),
            ("with open('o','w') as f:\n    f.write('x')", ['o']),
            ("open('/tmp/x','w')", ['/tmp/x']), ("open('~/x','w')", ['~/x']),
            ("import io\nio.open('o','w')", ['o']),
            ("import codecs\ncodecs.open('o','w','utf-8')", ['o']),
            ("import os\nos.open('o', os.O_WRONLY)", ['o']), ("import os\nos.open('o', os.O_RDWR)", ['o']),
            ("import os\nos.open('o', os.O_CREAT | os.O_APPEND)", ['o']),
            ("import os\nos.open('o', os.O_TRUNC)", ['o']), ("import os\nos.open('o', os.O_RDONLY)", []),
            ("import os\nos.open('o', f)", None),
        ])
        for name in ('remove', 'unlink', 'rmdir', 'removedirs', 'mkdir', 'makedirs', 'mkfifo'):
            self.py([(f"import os\nos.{name}('a')", ['a'])])
        self.py([
            ("import os\nos.truncate('a', 0)", ['a']),
            ("import os\nos.rename('a','b')", ['a', 'b']), ("import os\nos.renames('a','b')", ['a', 'b']),
            ("import os\nos.replace('a','b')", ['a', 'b']),
            ("import os\nos.symlink('a','b')", ['b']), ("import os\nos.link('a','b')", ['b']),
        ])
        for name in ('copy', 'copy2', 'copyfile', 'copytree'):
            self.py([(f"import shutil\nshutil.{name}('a','b')", ['b'])])
        self.py([
            ("import shutil\nshutil.move('a','b')", ['a', 'b']), ("import shutil\nshutil.rmtree('a')", ['a']),
        ])
        head = 'from pathlib import Path\n'
        for name, args in (('write_text', "'y'"), ('write_bytes', "b'y'"), ('touch', ''), ('mkdir', ''),
                           ('unlink', ''), ('rmdir', ''), ('symlink_to', "'t'"), ('hardlink_to', "'t'")):
            self.py([(f"{head}Path('x').{name}({args})", ['x'])])
        self.py([
            (head + "Path('x').rename('y')", ['x', 'y']), (head + "Path('x').replace('y')", ['x', 'y']),
            (head + "Path('x').open('w')", ['x']), (head + "Path('x').open('rb')", []), (head + "Path('x').open()", []),
            (head + "Path('x').read_text()", []), ("import pathlib\npathlib.Path('x').touch()", ['x']),
            (head + "Path('a', 'b').touch()", ['a/b']),
        ])

    def test_interpreter_python_aliases_and_receivers(self):
        self.py([
            ("import os as o\no.remove('a')", ['a']), ("from os import remove\nremove('a')", ['a']),
            ("from os import remove as rm\nrm('a')", ['a']), ("from pathlib import Path as P\nP('x').touch()", ['x']),
            ("import shutil as sh\nsh.rmtree('a')", ['a']), ("from shutil import rmtree\nrmtree('a')", ['a']),
            ("from os import *\nremove('a')", ['a']), ("from pathlib import *\nPath('x').touch()", ['x']),
            ("import os.path\nos.remove('a')", ['a']),
            ("p.touch()", None), ("x.write_text('y')", None),
            ("from pathlib import Path\nPath('a').parent.mkdir()", None),
            ("from pathlib import Path\nPath(p).write_text('y')", None),
            ("from pathlib import Path\np = Path('a')\np.unlink()", None),
            ("'a'.replace('a','b')", []), ("s.rename('x')", []), ("f.open('w')", []), ("os.path.join('a', 'b')", []),
        ])

    def test_interpreter_python_names_in_text_are_not_calls(self):
        self.py([
            ("print(\"open('o','w')\")", []), ("# open('o','w')\nprint(1)", []), ("x = 'os.remove'", []),
            ("'''open('o','w')'''", []),
        ])

    def test_interpreter_python_unparsable_code(self):
        self.py([("open('o','w'", None), ("print(1", []), ("import os\nos.remove('a'", None), ("def (", []),
                 ("print 'x'", [])])

    def test_interpreter_chdir_with_a_write_is_none(self):
        self.py([("import os\nos.chdir('d')\nopen('o','w')", None), ("import os\nos.chdir('d')", []),
                 ("from os import chdir\nchdir('d')\nopen('o','w')", None)])
        self.node([("process.chdir('d'); fs.writeFileSync('o','x')", None), ("process.chdir('d')", [])])
        self.rb([("Dir.chdir('d'); File.write('o','x')", None), ("Dir.chdir('d')", [])])
        self.pl([("chdir 'd'; unlink 'a'", None), ("chdir 'd'", [])])

    def test_interpreter_devices_are_no_write(self):
        self.py([("open('/dev/null','w')", []), ("open('/dev/stdout','w')", []), ("open('/dev/stderr','a')", []),
                 ("open('/dev/null','w'); open('o','w')", ['o'])])
        self.node([("fs.writeFileSync('/dev/null','x')", []), ("fs.writeFileSync('/dev/stdout','x')", [])])
        self.rb([("File.write('/dev/null','x')", []), ("File.write('/dev/stderr','x')", [])])
        self.pl([("open(F, '>', '/dev/null')", []), ("open(F, '>/dev/stdout')", [])])

    def test_interpreter_node_write_forms(self):
        for name in ('writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'createWriteStream'):
            self.node([(f"fs.{name}('o','x')", ['o'])])
        for name in ('mkdir', 'mkdirSync', 'mkdtemp', 'mkdtempSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'unlink',
                     'unlinkSync', 'truncate', 'truncateSync'):
            self.node([(f"fs.{name}('a')", ['a'])])
        for name in ('rename', 'renameSync'):
            self.node([(f"fs.{name}('a','b')", ['a', 'b'])])
        for name in ('copyFile', 'copyFileSync', 'cp', 'cpSync', 'symlink', 'symlinkSync', 'link', 'linkSync'):
            self.node([(f"fs.{name}('a','b')", ['b'])])
        self.node([
            ("fs.openSync('o','w')", ['o']), ("fs.open('o','a', cb)", ['o']), ("fs.openSync('o','r+')", ['o']),
            ("fs.openSync('o','r')", []), ("fs.openSync('o')", []), ("fs.openSync('o', m)", None),
            ("fs.promises.writeFile('o','x')", ['o']), ("await fs.rm('a', {recursive: true})", ['a']),
            ("fs.writeFileSync(`o`, 'x')", ['o']), ("fs.writeFileSync(`o${x}`, 'x')", None),
            ("fs.readFileSync('a')", []), ("fs.existsSync('a')", []),
        ])
        for head, code, want in (("import fs from 'fs';", "fs.writeFileSync('o','x')", 'o'),
                                 ("import {writeFileSync} from 'node:fs';", "writeFileSync('o','x')", 'o'),
                                 ("const {rm} = require('node:fs');", "rm('a')", 'a'),
                                 ("const fsp = require('fs/promises');", "fsp.writeFile('o','x')", 'o'),
                                 ("import * as fsp from 'node:fs/promises';", "fsp.writeFile('o','x')", 'o')):
            with self.subTest(code=head + code):
                self.assertEqual(iw('node -e ' + Q(head + code)), [P('/p/' + want)])

    def test_interpreter_node_needs_the_fs_module(self):
        for code in ("db.writeFile('o','x')", "console.log(1)", "const path = require('path'); fs.rmSync('a')"):
            with self.subTest(code=code):
                self.assertEqual(iw('node -e ' + Q(code)), [])
        self.node([("console.log(\"fs.writeFileSync('o','x')\")", []), ("// fs.rmSync('a')", []),
                   ("/* fs.rmSync('a') */ 1", []), ("fs.writeFileSync('o', 'fs.rmSync(\"a\")')", ['o'])])

    def test_interpreter_node_option_forms(self):
        for opts in ('-p', '--eval', '--print', '-pe', '-e', '-r path -e', '--input-type=module -e'):
            with self.subTest(opts=opts):
                self.assertEqual(iw(f"node {opts} " + Q("require('fs').rmSync('a')")), [P('/p/a')])
        self.assertEqual(iw('node --eval=' + Q("require('fs').rmSync('a')")), [P('/p/a')])

    def test_interpreter_ruby_write_forms(self):
        for cls, name in (('File', 'write'), ('File', 'binwrite'), ('IO', 'write'), ('IO', 'binwrite')):
            self.rb([(f"{cls}.{name}('o','x')", ['o']), (f"{cls}.{name} 'o', 'x'", ['o'])])
        for name in ('delete', 'unlink'):
            self.rb([(f"File.{name}('a')", ['a']), (f"File.{name} 'a'", ['a']), (f"File.{name}('a','b')", ['a', 'b'])])
        self.rb([
            ("File.open('o','w')", ['o']), ("File.new('o','a')", ['o']), ("File.open('o','r+')", ['o']),
            ("File.open('o')", []), ("File.open('o','r')", []), ("File.open('a', m)", None),
            ("File.open('o', 'w') { |f| f.puts 1 }", ['o']), ("File.open 'o', 'w' do |f| f.puts 1 end", ['o']),
            ("File.open('o', mode: 'w')", ['o']), ("File.read('a')", []),
            ("File.rename('a','b')", ['a', 'b']), ("File.symlink('a','b')", ['b']), ("File.link('a','b')", ['b']),
            ("File.truncate('a', 0)", ['a']),
            ("Dir.mkdir('a')", ['a']), ("Dir.rmdir('a')", ['a']), ("Dir.delete('a')", ['a']),
            ("Dir.unlink('a')", ['a']), ("Dir.glob('a')", []),
        ])
        for name in ('rm', 'rm_f', 'rm_r', 'rm_rf', 'rmtree', 'remove', 'remove_dir', 'remove_file', 'rmdir', 'mkdir',
                     'mkdir_p', 'makedirs', 'mkpath', 'touch'):
            self.rb([(f"FileUtils.{name} 'a'", ['a']), (f"FileUtils.{name}('a')", ['a'])])
        for name in ('mv', 'move'):
            self.rb([(f"FileUtils.{name} 'a', 'b'", ['a', 'b'])])
        for name in ('cp', 'copy', 'cp_r', 'copy_file', 'install', 'ln', 'ln_s', 'ln_sf', 'symlink'):
            self.rb([(f"FileUtils.{name} 'a', 'b'", ['b'])])

    def test_interpreter_ruby_names_in_text_are_not_calls(self):
        self.rb([('puts "File.write is a method"', []), ("# File.write('o','x')\nputs 1", []),
                 ("puts 'FileUtils.rm_rf d' if line =~ /File.write/", []), ("x = :write", []),
                 ("File.write('o','x') # File.delete('a')", ['o'])])

    def test_interpreter_ruby_several_e_options_are_joined(self):
        self.assertEqual(iw('ruby -e ' + Q('x = 1') + ' -e ' + Q("File.write('o','x')")), [P('/p/o')])
        self.assertEqual(iw('ruby -ne ' + Q("File.write('o','x')")), [P('/p/o')])
        self.assertEqual(iw('ruby -w -I lib -rjson -e ' + Q("File.write('o','x')")), [P('/p/o')])

    def test_interpreter_perl_write_forms(self):
        self.pl([
            ("open(my $f, '>', 'o')", ['o']), ("open(F, '>>log.txt')", ['log.txt']), ("open F, '>o' or die", ['o']),
            ("open(my $f, '+<', 'o')", ['o']), ("open(my $f, '+>', 'o')", ['o']), ("open(my $f, '>>', 'o')", ['o']),
            ("open(my $f, '>:utf8', 'o')", ['o']), ("open(F, '+>>o')", ['o']), ("open(F, '> o')", ['o']),
            ("open(F, '<', 'a')", []), ("open(F, 'a')", []), ("open(F, '<a')", []), ("open(F, '-|', 'ls')", []),
            ('open(F, ">log")', ['log']),
            ("sysopen(F, 'o', O_WRONLY|O_CREAT)", ['o']), ("sysopen(F, 'o', O_RDONLY)", []),
            ("sysopen(F, 'o', $fl)", None),
            ("unlink 'a'", ['a']), ("unlink('a','b')", ['a', 'b']), ("rename('a','b')", ['a', 'b']),
            ("mkdir 'd'", ['d']), ("rmdir 'd'", ['d']), ("link('a','b')", ['b']), ("symlink('a','b')", ['b']),
            ("truncate('a', 0)", ['a']),
            ("use File::Copy; copy('a','b')", ['b']), ("use File::Copy; cp('a','b')", ['b']),
            ("use File::Copy; move('a','b')", ['a', 'b']), ("use File::Copy; mv('a','b')", ['a', 'b']),
            ("copy('a','b')", []), ("move('a','b')", []),
            ("use File::Path qw(make_path); make_path('a/b')", ['a/b']), ("use File::Path; mkpath('a')", ['a']),
            ("use File::Path; remove_tree('a')", ['a']), ("use File::Path; rmtree('a')", ['a']),
            ("use File::Path; make_path('a', 'b', {mode => 0711})", ['a', 'b']),
            ('print "open(F, \'>x\')\\n"', []), ("# unlink 'a'\nprint 1", []), ("$h{unlink} = 1", []),
            ("$fh->open('>x')", []), ("print if /unlink 'a'/", []), ("print if m{open(F, '>x')}", []),
        ])
        self.assertEqual(iw('perl -MFile::Copy -e ' + Q("copy('a','b')")), [P('/p/b')])
        self.assertEqual(iw('perl -MFile::Path=make_path -e ' + Q("make_path('a')")), [P('/p/a')])

    def test_interpreter_perl_option_clusters(self):
        for opts in ('-e', '-E', '-ne', '-lne', '-lane', '-pe', '-0777ne', '-Mre -e', '-Ilib/e -e', '-I lib -e',
                     '-F: -lane', '-wle', '-CS -e'):
            with self.subTest(opts=opts):
                self.assertEqual(iw(f"perl {opts} " + Q("unlink 'a'")), [P('/p/a')])
        self.assertEqual(iw('perl -e ' + Q('1') + ' -e ' + Q("unlink 'a'")), [P('/p/a')])

    def test_interpreter_python_option_forms(self):
        code = Q("open('o','w')")
        for head in ('python3 -c', 'python -c', 'python3.12 -c', '/usr/bin/python3 -c', 'python3 -u -c', 'python3 -Sc',
                     'python3 -W ignore -c', 'python3 -X dev -c', 'python3 -I -B -c'):
            with self.subTest(head=head):
                self.assertEqual(iw(f'{head} {code}'), [P('/p/o')])
        self.assertEqual(iw('python3 -c' + code), [P('/p/o')])
        self.assertEqual(iw('python3 -c'), [])

    def test_interpreter_heredoc_code(self):
        body = "open('o.txt','w').write('x')"
        for head in ("python3 - <<'EOF'", "python3 <<'EOF'", "python3 <<EOF", "python3 <<\"EOF\"", "python <<EOF",
                     "sudo python3 - <<'EOF'", "env FOO=1 python3 - <<'EOF'"):
            with self.subTest(head=head):
                self.assertEqual(iw(f"{head}\n{body}\nEOF"), [P('/p/o.txt')])
        self.assertEqual(iw("node <<EOF\nrequire('fs').writeFileSync('o','x')\nEOF"), [P('/p/o')])
        self.assertEqual(iw("node - <<'EOF'\nrequire('fs').writeFileSync('o','x')\nEOF"), [P('/p/o')])
        self.assertEqual(iw("ruby <<EOF\nFile.write('o','x')\nEOF"), [P('/p/o')])
        self.assertEqual(iw("perl <<'EOF'\nunlink 'a';\nEOF"), [P('/p/a')])
        self.assertEqual(iw("python3 <<-'EOF'\n\topen('o','w')\n\tEOF"), [P('/p/o')])
        self.assertEqual(iw("cd sub && python3 - <<'EOF'\nopen('o','w')\nEOF"), [P('/p/sub/o')])
        self.assertEqual(iw("python3 - <<'A'\nopen('a','w')\nA\npython3 - <<'B'\nopen('b','w')\nB"),
                         [P('/p/a'), P('/p/b')])
        self.assertEqual(iw("cat <<'A' && python3 - <<'B'\nopen('a','w')\nA\nopen('b','w')\nB"), [P('/p/b')])
        self.assertEqual(iw("python3 - <<'EOF' > out.log\nopen('x','w')\nEOF"), [P('/p/x')])
        # the same heredoc fed to something else is text
        for cmd in ("cat <<'EOF'\nopen('x','w')\nEOF", "cat <<'EOF' | python3 -\nopen('x','w')\nEOF",
                    "cat > f.py <<'EOF'\nopen('x','w')\nEOF", "python3 - <<'EOF'\nprint(1)\nEOF",
                    "python3 -c 'print(1)' <<'EOF'\nopen('x','w')\nEOF", "python3 tool.py <<'EOF'\nopen('x','w')\nEOF",
                    "python3 -m pkg <<'EOF'\nopen('x','w')\nEOF", "python3 - < in.py"):
            with self.subTest(cmd=cmd):
                self.assertEqual(iw(cmd), [])
        # what the heredoc handling cannot follow fails closed, as write_targets does
        self.assertIsNone(iw("python3 - <<EOF\n$(printenv)\nEOF"))
        self.assertIsNone(iw("python3 - <<'EOF'\nopen('x','w')"))

    def test_interpreter_behind_prefix_words(self):
        code = 'python3 -c ' + Q("open('o','w')")
        for prefix in ('sudo', 'sudo -u root', 'sudo -i', 'doas', 'env', 'env -i', 'env FOO=1', 'command', 'time',
                       'nohup', 'nice', 'nice -n 5', 'exec', 'builtin', 'timeout 5', 'timeout -s KILL 5', 'xargs',
                       'xargs -n 1', 'xargs -t', 'setsid', 'FOO=1 sudo env nohup'):
            with self.subTest(prefix=prefix):
                self.assertEqual(iw(f'{prefix} {code}'), [P('/p/o')])
        for spliced in ("p'y'thon3 -c ", 'pyth\\on3 -c ', '"python3" -c ', "py''thon3 -c "):
            with self.subTest(spliced=spliced):
                self.assertEqual(iw(spliced + Q("open('o','w')")), [P('/p/o')])
        self.assertEqual(iw('bash -c ' + Q(code)), [P('/p/o')])
        self.assertEqual(iw('eval ' + Q(code)), [P('/p/o')])
        self.assertEqual(iw('sh -c ' + Q('cd sub && ' + code)), [P('/p/o'), P('/p/sub/o')])   # a `cd` in a string
        # xargs with a replace option: the code text can change
        for replace in ('-I{}', '-I {}', '-i', '-i{}', '--replace', '--replace={}', '-tI {}', '-n1 -I {}'):
            with self.subTest(replace=replace):
                self.assertIsNone(iw(f'xargs {replace} python3 -c ' + Q("open('{}','w')")))
        self.assertIsNone(iw('echo a | xargs -I{} node -e ' + Q("require('fs').rmSync('{}')")))
        self.assertIsNone(iw('xargs -I{} python3 -c ' + Q("print(1)")))
        self.assertEqual(iw('xargs -I{} python3 tool.py {}'), [])
        self.assertEqual(iw('xargs -I{} echo {}'), [])
        self.assertEqual(iw('sudo -i python3 -c ' + Q('print(1)')), [])
        self.assertEqual(iw('env -i python3 -c ' + Q('print(1)')), [])

    def test_interpreter_non_literal_paths_are_refused(self):
        self.py([("open(p,'w')", None), ("open('a', m)", None), ("open('a', 'w' if x else 'r')", None),
                 ("p.write_text('y')", None), ("open(f'{x}','w')", None), ("open('a'+b,'w')", None),
                 ("open('%s' % x,'w')", None), ("open('a{}'.format(1),'w')", None), ("open('a$b','w')", None),
                 ("open('a@b','w')", None), ("import os\nos.remove(p)", None), ("import os\nos.rename('a', p)", None),
                 ("import shutil\nshutil.copy('a')", None), ("open(*args)", None), ("open(**kw)", None),
                 ("open(b'a','w')", None)])
        self.node([("fs.rmSync(dir)", None), ("fs.writeFileSync('a'+b,'x')", None),
                   ("fs.writeFileSync(path.join('a','b'),'x')", None), ("fs.writeFileSync('a$b','x')", None)])
        self.rb([("File.write(p,'x')", None), ('File.write("a#{x}",\'x\')', None), ("File.write('a'+b,'x')", None),
                 ("File.write('a@b','x')", None), ("FileUtils.rm_rf dir", None), ("FileUtils.rm(['a','b'])", None)])
        self.pl([("open(F, '>', $p)", None), ("open(F, $m, 'a')", None), ("unlink @files", None),
                 ('open(F, ">$f")', None), ("open(F, $spec)", None), ("unlink $f", None), ("mkdir $d", None)])
        self.assertIsNone(iw('python3 -c "open(\'$F\',\'w\')"'))
        # one literal and one non-literal write together
        self.py([("open('a','w'); open(p,'w')", None), ("open(p,'w'); open('a','w')", None),
                 ("import os\nos.remove('a')\nos.remove(p)", None)])
        self.node([("fs.writeFileSync('a','x'); fs.rmSync(dir)", None)])
        self.pl([("unlink 'a'; unlink $f", None)])
        self.assertIsNone(iw('python3 -c "open(\'a\',\'w\')"; python3 -c "open(p,\'w\')"'))
        # a symlink made in the same command as a visible write
        self.assertIsNone(iw('ln -s /x d && python3 -c "open(\'d/o\',\'w\')"'))
        self.assertEqual(iw('ln -s /x d && python3 -c "print(1)"'), [])
        self.assertEqual(iw('ln -s /x d'), [])

    def test_interpreter_script_file_is_not_read(self):
        for cmd in ('python3 tool.py', 'python3 -m pkg', 'node x.js', 'ruby x.rb', 'perl x.pl', 'python3 tool.py -c x',
                    'python3 -m pkg -c "open(\'o\',\'w\')"', 'python3 ./tool.py "open(\'o\',\'w\')"',
                    'node x.js -e "require(\'fs\').rmSync(\'a\')"', 'python3 -u tool.py', 'perl x.pl -e 1',
                    'python3 -m unittest', 'python3 -'):
            with self.subTest(cmd=cmd):
                self.assertEqual(iw(cmd), [])

    def test_interpreter_stated_limits_are_not_followed(self):
        self.py([("import os\nos.system('rm a')", []), ("import subprocess\nsubprocess.run(['rm','a'])", []),
                 ("exec(\"open('o','w')\")", []), ("eval(\"open('o','w')\")", []),
                 ("getattr(__import__('os'), 'remove')('a')", []), ("__import__('os').remove('a')", [])])
        self.node([("require('child_process').execSync('rm a')", []), ("eval(\"fs.rmSync('a')\")", [])])
        self.rb([("system('rm a')", []), ("`rm a`", []), ("eval(\"File.write('o','x')\")", [])])
        self.pl([("system('rm a')", []), ("`rm a`", []), ("eval \"unlink 'a'\"", [])])
        self.assertEqual(iw('python3 <<< "open(\'o\',\'w\')"'), [])
        self.assertEqual(iw('perl -i -pe ' + Q('s/a/b/') + ' f.txt'), [])
        self.assertEqual(iw('ruby -i -pe ' + Q('$_.upcase!') + ' f.txt'), [])
        self.assertEqual(iw('perl -pi -e ' + Q('s/a/b/') + ' f.txt'), [])

    def test_interpreter_cd_folders_apply(self):
        self.assertEqual(iw('cd sub && python3 -c ' + Q("open('o','w')")), [P('/p/sub/o')])
        self.assertEqual(iw('cd sub; python3 -c ' + Q("open('o','w')")), [P('/p/o'), P('/p/sub/o')])
        self.assertIsNone(iw('cd "$D" && python3 -c ' + Q("open('o','w')")))

    def test_interpreter_without_an_interpreter_word_is_empty(self):
        for cmd in ('echo hi', 'git status', 'cat a > b', 'git checkout -- x', 'echo "unterminated'):
            with self.subTest(cmd=cmd):
                self.assertEqual(iw(cmd), [])

    def test_write_targets_ignores_interpreter_code(self):
        rows = [
            'python3 -c ' + Q("open('o.txt','w')"),
            'python3 -c ' + Q("import os; os.remove('a'); os.rename('b','c')"),
            'python3 -c ' + Q("from pathlib import Path; Path('x.md').write_text('y')"),
            'node -e ' + Q("require('fs').writeFileSync('o','x')"),
            'ruby -e ' + Q("File.write('o','x')"), 'ruby -e ' + Q("FileUtils.rm_rf 'd'"),
            'perl -e ' + Q("open(my $f, '>', 'o')"), 'perl -e ' + Q("unlink 'a'"),
            'cd sub && python3 -c ' + Q("open('o','w')"),
            "python3 - <<'EOF'\nopen('o.txt','w').write('x')\nEOF",
            "node <<EOF\nrequire('fs').writeFileSync('o','x')\nEOF",
            'sudo python3 -c ' + Q("open('o','w')"), 'bash -c ' + Q('python3 -c ' + Q("open('o','w')")),
            'python3 -c ' + Q("open(p,'w')"),
        ]
        for cmd in rows:
            with self.subTest(cmd=cmd):
                self.assertEqual(ma_bash.write_targets(cmd, CWD), [])
        self.assertEqual(ma_bash.write_targets('cd sub && python3 -c ' + Q("open('o','w')") + ' > r.txt', CWD),
                         [P('/p/sub/r.txt')])

    def test_write_targets_docstring_says_it_does_not_read_interpreter_code(self):
        self.assertIn('does not read inline interpreter code', ' '.join(ma_bash.write_targets.__doc__.split()))

    def test_module_docstring_names_the_interpreter_limit(self):
        doc = ' '.join(ma_bash.__doc__.split())
        self.assertIn('interpreter_writes', doc)
        self.assertIn('scope-guard', doc)
        self.assertIn('script file', doc)
        self.assertIn('does not read inline interpreter code', doc)
        self.assertNotIn('a write it cannot see (`python -c`, a script) is the accepted', doc)


if __name__ == '__main__':
    unittest.main()
