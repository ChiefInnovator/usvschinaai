module.exports = {
  content: ['./*.html', './js/*.js'],
  safelist: [
    'text-blue-400', 'text-red-400', 'text-green-400', 'text-white',
    'bg-blue-500', 'bg-red-500', 'bg-green-500', 'bg-slate-800',
    'bg-blue-500/10', 'bg-red-500/10', 'bg-blue-500/5', 'bg-red-500/5',
    'bg-blue-500/20', 'bg-red-500/20', 'bg-green-500/20',
    'border-blue-500/20', 'border-red-500/20', 'border-blue-500/30',
    'border-red-500/30', 'ring-blue-400', 'ring-red-400',
    'ring-2', 'ring-offset-2', 'ring-offset-slate-900',
    'text-center', 'text-left', 'text-right', 'hidden', 'block', 'flex',
    'bg-slate-900/30', 'text-yellow-400', 'bg-yellow-500/10',
    'border-yellow-500/20'
  ],
  theme: {extend: {}},
  plugins: []
};
