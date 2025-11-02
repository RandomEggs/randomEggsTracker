const workDurationDefault = 25 * 60; // seconds
const breakDurationDefault = 5 * 60; // seconds

let workDuration = workDurationDefault;
let breakDuration = breakDurationDefault;
let timeRemaining = workDuration;
let isRunning = false;
let isWorkPhase = true;
let timerInterval = null;
let activeSessionId = null;
let notificationsGranted = false;

const timerDisplay = document.getElementById('timer-display');
const timerPhase = document.getElementById('timer-phase');
const startButton = document.getElementById('start-btn');
const pauseButton = document.getElementById('pause-btn');
const resetButton = document.getElementById('reset-btn');
const workInput = document.getElementById('work-duration');
const breakInput = document.getElementById('break-duration');
const progressCircle = document.getElementById('progress-circle');
const progressText = document.getElementById('progress-text');
const toastContainer = document.getElementById('toast-container');
const chartCanvas = document.getElementById('stats-chart');

let chartInstance = null;

async function fetchTasks() {
  const response = await fetch('/tasks');
  const tasks = await response.json();
  renderTasks(tasks);
}

function renderTasks(tasks) {
  const taskList = document.getElementById('task-list');
  taskList.innerHTML = '';
  tasks.forEach(task => {
    const li = document.createElement('li');
    li.classList.add('flex', 'items-center', 'justify-between', 'p-3', 'rounded-lg', 'bg-slate-800/60', 'border', 'border-slate-700/60');
    li.innerHTML = `
      <div class="flex flex-col">
        <span class="font-semibold">${task.title}</span>
        <span class="text-xs text-slate-400">${new Date(task.created_at).toLocaleString()}</span>
      </div>
      <div class="flex gap-2 items-center">
        <select data-task-id="${task.id}" class="task-status text-sm bg-slate-900 border border-slate-700 rounded px-2 py-1">
          <option value="pending" ${task.status === 'pending' ? 'selected' : ''}>Pending</option>
          <option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
          <option value="done" ${task.status === 'done' ? 'selected' : ''}>Done</option>
        </select>
        <button data-task-id="${task.id}" class="delete-task btn btn-primary bg-rose-500 hover:bg-rose-600 py-1 px-3 text-sm">Delete</button>
      </div>
    `;
    taskList.appendChild(li);
  });
  syncActiveTaskOptions(tasks);
}

function syncActiveTaskOptions(tasks) {
  const select = document.getElementById('active-task');
  if (!select) return;
  const previousValue = select.value;
  select.innerHTML = '<option value="">No task selected</option>';
  tasks.forEach(task => {
    const option = document.createElement('option');
    option.value = task.id;
    option.textContent = task.title;
    select.appendChild(option);
  });
  if (previousValue) {
    const match = tasks.find(task => String(task.id) === previousValue);
    select.value = match ? previousValue : '';
  }
}

async function addTask(event) {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  const response = await fetch('/add', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    form.reset();
    fetchTasks();
  }
}

async function updateTaskStatus(taskId, status) {
  await fetch(`/update/${taskId}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status})
  });
  fetchTasks();
}

async function deleteTask(taskId) {
  await fetch(`/delete/${taskId}`, {method: 'POST'});
  fetchTasks();
}

function formatTime(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function updateDisplay() {
  timerDisplay.textContent = formatTime(timeRemaining);
  timerPhase.textContent = isWorkPhase ? 'Focus' : 'Break';
  const total = isWorkPhase ? workDuration : breakDuration;
  const progress = 1 - timeRemaining / total;
  progressCircle.style.strokeDashoffset = `${circumference * (1 - progress)}`;
  progressText.textContent = `${Math.round(progress * 100)}%`;
}

const circumference = 2 * Math.PI * 54;
progressCircle.style.strokeDasharray = `${circumference}`;
progressCircle.style.strokeDashoffset = `${circumference}`;

async function startTimer() {
  if (isRunning) return;
  if (!notificationsGranted && 'Notification' in window) {
    Notification.requestPermission().then(permission => {
      notificationsGranted = permission === 'granted';
    });
  }
  isRunning = true;
  startButton.disabled = true;
  pauseButton.disabled = false;
  resetButton.disabled = false;

  if (!activeSessionId && isWorkPhase) {
    const response = await fetch('/api/pomodoro/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({task_id: getSelectedTaskId()})
    });
    if (response.ok) {
      const data = await response.json();
      activeSessionId = data.session_id;
    }
  }

  timerInterval = setInterval(async () => {
    timeRemaining -= 1;
    if (timeRemaining <= 0) {
      clearInterval(timerInterval);
      timerInterval = null;
      await handlePhaseCompletion();
    }
    updateDisplay();
  }, 1000);
}

function getSelectedTaskId() {
  const select = document.getElementById('active-task');
  return select && select.value ? Number(select.value) : null;
}

async function pauseTimer() {
  if (!isRunning) return;
  isRunning = false;
  startButton.disabled = false;
  pauseButton.disabled = true;
  clearInterval(timerInterval);
}

async function resetTimer() {
  isRunning = false;
  clearInterval(timerInterval);
  timerInterval = null;
  activeSessionId = null;
  isWorkPhase = true;
  timeRemaining = workDuration;
  updateDisplay();
  startButton.disabled = false;
  pauseButton.disabled = true;
  resetButton.disabled = true;
}

async function handlePhaseCompletion() {
  if (isWorkPhase) {
    await completeSession();
    showToast('Focus session complete! Time for a break.');
    notifyUser('Focus session done!', 'Take a short break.');
    isWorkPhase = false;
    timeRemaining = breakDuration;
    startTimer();
  } else {
    showToast('Break complete! Ready for another focus session.');
    notifyUser('Break over', 'Ready to focus again?');
    isWorkPhase = true;
    timeRemaining = workDuration;
    startTimer();
  }
}

async function completeSession() {
  if (!activeSessionId) return;
  await fetch(`/api/pomodoro/end/${activeSessionId}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({duration: workDuration - timeRemaining})
  });
  activeSessionId = null;
  refreshStats();
}

function applyCustomDurations() {
  const workMinutes = parseInt(workInput.value, 10);
  const breakMinutes = parseInt(breakInput.value, 10);
  if (!Number.isNaN(workMinutes) && workMinutes > 0) {
    workDuration = workMinutes * 60;
  }
  if (!Number.isNaN(breakMinutes) && breakMinutes > 0) {
    breakDuration = breakMinutes * 60;
  }
  timeRemaining = isWorkPhase ? workDuration : breakDuration;
  updateDisplay();
}

function showToast(message) {
  if (!toastContainer) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

function notifyUser(title, body) {
  if (notificationsGranted) {
    new Notification(title, {body});
  }
}

async function refreshStats() {
  const response = await fetch('/api/pomodoro/stats');
  if (!response.ok) return;
  const stats = await response.json();
  renderChart(stats);
}

function renderChart(stats) {
  const dates = stats.map(s => s.date);
  const durations = stats.map(s => Math.round((s.total_duration || 0) / 60));
  if (chartInstance) {
    chartInstance.destroy();
  }
  chartInstance = new Chart(chartCanvas, {
    type: 'bar',
    data: {
      labels: dates,
      datasets: [
        {
          label: 'Focus minutes',
          data: durations,
          backgroundColor: 'rgba(99, 102, 241, 0.6)',
          borderColor: 'rgba(129, 140, 248, 0.8)',
          borderWidth: 1,
          borderRadius: 6
        }
      ]
    },
    options: {
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            color: '#cbd5f5'
          },
          grid: {
            color: 'rgba(148, 163, 184, 0.2)'
          }
        },
        x: {
          ticks: {
            color: '#cbd5f5'
          },
          grid: {
            display: false
          }
        }
      },
      plugins: {
        legend: {
          labels: {
            color: '#e2e8f0'
          }
        }
      }
    }
  });
}

function bindEvents() {
  document.getElementById('task-form').addEventListener('submit', addTask);
  document.getElementById('task-list').addEventListener('change', event => {
    if (event.target.classList.contains('task-status')) {
      updateTaskStatus(event.target.dataset.taskId, event.target.value);
    }
  });
  document.getElementById('task-list').addEventListener('click', event => {
    if (event.target.classList.contains('delete-task')) {
      deleteTask(event.target.dataset.taskId);
    }
  });

  startButton.addEventListener('click', startTimer);
  pauseButton.addEventListener('click', pauseTimer);
  resetButton.addEventListener('click', resetTimer);
  workInput.addEventListener('change', applyCustomDurations);
  breakInput.addEventListener('change', applyCustomDurations);
}

function init() {
  if (!timerDisplay) return;
  bindEvents();
  fetchTasks();
  refreshStats();
  updateDisplay();
  pauseButton.disabled = true;
  resetButton.disabled = true;
}

document.addEventListener('DOMContentLoaded', init);
