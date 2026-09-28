const form = document.querySelector('#run-form');
const runButton = document.querySelector('#run-button');
const formError = document.querySelector('#form-error');
const statusPill = document.querySelector('#status-pill');
const runMessage = document.querySelector('#run-message');
const progressFill = document.querySelector('#progress-fill');
const progressLabel = document.querySelector('#progress-label');
const runLog = document.querySelector('#run-log');
const outputs = document.querySelector('#outputs');
const updateDepara = document.querySelector('#update-depara');
const elapsed = document.querySelector('#elapsed');
const themeToggle = document.querySelector('#theme-toggle');
let startedAt = null;
let pollTimer = null;

function applyTheme(theme) {
  const isDark = theme === 'dark';
  document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
  themeToggle.setAttribute('aria-pressed', String(isDark));
  themeToggle.setAttribute('aria-label', isDark ? 'Ativar modo claro' : 'Ativar modo escuro');
  themeToggle.querySelector('.theme-label').textContent = isDark ? 'Claro' : 'Escuro';
  document.querySelector('meta[name="theme-color"]').content = isDark ? '#141b17' : '#f1f3ef';
}

applyTheme(document.documentElement.dataset.theme || 'light');
themeToggle.addEventListener('click', () => {
  const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(nextTheme);
  try {
    localStorage.setItem('aprovadores-theme', nextTheme);
  } catch (_error) {}
});

function setError(message) {
  formError.textContent = message;
  formError.hidden = !message;
}

function setStatus(status, message) {
  const labels = {
    idle: 'AGUARDANDO',
    queued: 'NA FILA',
    running: 'PROCESSANDO',
    completed: 'CONCLUÍDO',
    failed: 'COM ERRO',
  };
  statusPill.className = `status-pill ${status}`;
  statusPill.querySelector('span').textContent = labels[status] || status.toUpperCase();
  runMessage.textContent = message;
  progressFill.className = status === 'running' || status === 'queued' ? 'active' : status === 'completed' ? 'done' : '';
  progressLabel.textContent = status === 'completed'
    ? 'ARQUIVOS PRONTOS'
    : status === 'failed'
      ? 'VERIFIQUE O REGISTRO'
      : status === 'queued'
        ? 'AGUARDANDO VAGA'
        : status === 'running'
          ? 'AUTOMAÇÃO EM CURSO'
          : 'PRONTO PARA INICIAR';
}

function formatElapsed() {
  if (!startedAt) return '--:--';
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  const minutes = String(Math.floor(seconds / 60)).padStart(2, '0');
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

for (const slot of document.querySelectorAll('.file-slot')) {
  const input = slot.querySelector('input');
  const name = slot.querySelector('.file-name');

  const showFile = (file) => {
    if (!file) return;
    name.textContent = file.name;
    slot.classList.add('has-file');
  };

  input.addEventListener('change', () => showFile(input.files[0]));
  slot.addEventListener('dragover', (event) => {
    event.preventDefault();
    slot.classList.add('drag-over');
  });
  slot.addEventListener('dragleave', () => slot.classList.remove('drag-over'));
  slot.addEventListener('drop', (event) => {
    event.preventDefault();
    slot.classList.remove('drag-over');
    const file = event.dataTransfer.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    showFile(file);
  });
}

updateDepara.addEventListener('change', () => {
  const rhInput = form.elements.rh;
  rhInput.required = updateDepara.checked;
  rhInput.closest('.file-slot').classList.toggle('needs-file', updateDepara.checked && !rhInput.files.length);
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  setError('');
  if (!form.reportValidity()) return;
  if (updateDepara.checked && !form.elements.rh.files.length) {
    setError('Selecione a base RH para atualizar o DePara.');
    form.elements.rh.focus();
    return;
  }

  runButton.disabled = true;
  runButton.querySelector('span:first-child').textContent = 'Preparando arquivos';
  outputs.hidden = true;
  runLog.textContent = 'Enviando arquivos para o processamento local...';
  startedAt = Date.now();
  setStatus('queued', 'Arquivos recebidos. O processamento começará em instantes.');

  try {
    const payload = new FormData(form);
    payload.set('atualizar_depara', updateDepara.checked ? 'true' : 'false');
    const response = await fetch('/api/runs', { method: 'POST', body: payload });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível iniciar a automação.');
    await pollRun(result.id);
  } catch (error) {
    setStatus('failed', error.message);
    runLog.textContent = error.message;
    runButton.disabled = false;
    runButton.querySelector('span:first-child').textContent = 'Tentar novamente';
  }
});

async function pollRun(runId) {
  const update = async () => {
    try {
      const response = await fetch(`/api/runs/${runId}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('Não foi possível consultar a execução.');
      const job = await response.json();
      setStatus(job.status, job.message);
      runLog.textContent = job.log.join('') || 'Aguardando saída do processo...';
      runLog.scrollTop = runLog.scrollHeight;
      elapsed.textContent = formatElapsed();

      if (job.status === 'completed') {
        outputs.hidden = false;
        for (const link of outputs.querySelectorAll('[data-kind]')) {
          link.href = `/api/runs/${runId}/files/${link.dataset.kind}`;
        }
        runButton.disabled = false;
        runButton.querySelector('span:first-child').textContent = 'Iniciar outro ciclo';
        clearInterval(pollTimer);
        return;
      }
      if (job.status === 'failed') {
        runButton.disabled = false;
        runButton.querySelector('span:first-child').textContent = 'Tentar novamente';
        clearInterval(pollTimer);
      }
    } catch (error) {
      setStatus('failed', error.message);
      clearInterval(pollTimer);
      runButton.disabled = false;
    }
  };

  await update();
  pollTimer = setInterval(update, 1500);
}
