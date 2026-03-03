import tseslint from 'typescript-eslint';

export default [
  {
    ignores: ['node_modules/', 'build/', '.venv/', '.ruff_cache/', 'src/ui/'],
  },
  ...tseslint.configs.recommended,
];
