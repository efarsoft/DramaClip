/**
 * 页面：导出预览
 */

import React from 'react';
import { Card, Typography } from 'antd';

const { Title } = Typography;

const ExportPage: React.FC = () => {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={2}>导出预览</Title>
      </div>

      <Card>
        <Typography.Text>导出预览功能开发中...</Typography.Text>
      </Card>
    </div>
  );
};

export default ExportPage;
