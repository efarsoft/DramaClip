import { execSync } from 'child_process';
const result = execSync('npx tsc --noEmit 2>&1', { cwd: 'D:\\DramaClip', encoding: 'utf-8' });
console.log(result);
